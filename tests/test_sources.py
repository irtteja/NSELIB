"""Offline tests for SourceRegistry — a fake NSE site is mutated between refreshes
to prove that new pages / endpoints / removals / breakage are detected and served
without any code change.  No network needed.
"""
import json
import pytest

from nselib.sources import SourceRegistry, _norm_api, _source_key, NSEDataError


class FakeResp:
    def __init__(self, status=200, text="", body=None, content=b""):
        self.status_code = status
        self.text = text if body is None else json.dumps(body)
        self.content = content or self.text.encode()
        self.headers = {"content-type": "application/json" if body is not None else "text/html"}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSite:
    """routes: path -> FakeResp. Mutate .routes between refresh() calls."""
    def __init__(self):
        self.routes = {}

    def page(self, path, chunks=()):
        scripts = "".join(f'<script src="/_next/static/chunks/{c}"></script>' for c in chunks)
        self.routes[path] = FakeResp(text=f"<html>{scripts}</html>")

    def sitemap(self, *paths):
        locs = "".join(f"<url><loc>https://www.nseindia.com{p}</loc></url>" for p in paths)
        self.routes["/sitemap.xml"] = FakeResp(text=f"<urlset>{locs}</urlset>")


@pytest.fixture
def env(tmp_path):
    site = FakeSite()
    reg = SourceRegistry(path=tmp_path / "sources.json")

    def fake_http(url_or_path, **kw):
        p = url_or_path
        if p.startswith("http"):
            p = "/" + p.split("/", 3)[3] if "nsearchives" not in p else p.replace("https://nsearchives.nseindia.com", "")
        return site.routes.get(p, FakeResp(404))

    reg._http = fake_http
    return site, reg


def _base_site(site):
    site.sitemap("/market-data/live-equity-market")
    site.routes["/"] = FakeResp(text="<html></html>")
    site.page("/market-data/live-equity-market", ["a.js"])
    site.routes["/_next/static/chunks/a.js"] = FakeResp(
        text='fetch("/api/NextApi/apiClient?functionName=getMarketTurnover");'
             'x=`/api/NextApi/apiClient/indexTrackerApi?functionName=getAdvanceDecline&&index=${e}`')
    site.routes["/api/NextApi/apiClient?functionName=getMarketTurnover"] = FakeResp(body={"data": [1]})


def test_key_and_normalisation():
    assert _norm_api("/api/allIndices") == "allIndices"
    assert _norm_api("https://www.nseindia.com/api/x?q=${e}") == "x?q={q}"
    assert _source_key("api", "NextApi/apiClient?functionName=foo&&a=1") == "api:NextApi/apiClient#foo"
    assert _source_key("archive", "/content/fo/fo_secban_09112026.csv") == "archive:/content/fo/fo_secban_{date}.csv"


def test_discovers_pages_sources_and_probes(env):
    site, reg = env
    _base_site(site)
    rep = reg.refresh()
    assert "/market-data/live-equity-market" in reg.pages()
    keys = {s["key"]: s for s in reg.sources()}
    assert keys["api:NextApi/apiClient#getMarketTurnover"]["probe"]["status"] == "ok"
    tpl = keys["api:NextApi/apiClient/indexTrackerApi#getAdvanceDecline"]
    assert tpl["probe"]["status"] == "template" and tpl["probe"]["params"] == ["index"]
    assert rep["sources"] == 2


def test_site_update_new_page_and_endpoint_become_accessible(env):
    site, reg = env
    _base_site(site)
    reg.refresh()
    # NSE ships a new page + a new JS chunk (new hash) with a brand-new endpoint
    site.sitemap("/market-data/live-equity-market", "/market-data/brand-new")
    site.page("/market-data/brand-new", ["b.js"])
    site.routes["/_next/static/chunks/b.js"] = FakeResp(
        text='fetch("/api/NextApi/apiClient/newApi?functionName=getShinyThing")')
    site.routes["/api/NextApi/apiClient/newApi?functionName=getShinyThing"] = FakeResp(body={"shiny": True})

    rep = reg.refresh()
    assert rep["new_pages"] == ["/market-data/brand-new"]
    assert rep["new_sources"] == ["api:NextApi/apiClient/newApi#getShinyThing"]
    assert reg.fetch("api:NextApi/apiClient/newApi#getShinyThing") == {"shiny": True}   # no code change
    assert rep["chunks_read"] == 1          # unchanged chunk a.js was NOT re-downloaded


def test_chunks_that_lazy_load_other_chunks_are_followed(env):
    site, reg = env
    _base_site(site)
    site.routes["/_next/static/chunks/a.js"] = FakeResp(text='import("/_next/static/chunks/lazy.js")')
    site.routes["/_next/static/chunks/lazy.js"] = FakeResp(text='"/api/deep?x=1"')
    site.routes["/api/deep?x=1"] = FakeResp(body=[{"a": 1}])
    reg.refresh()
    assert reg.data["sources"]["api:deep"]["probe"]["status"] == "ok"


def test_broken_and_recovered_detection(env):
    site, reg = env
    _base_site(site)
    reg.refresh()
    del site.routes["/api/NextApi/apiClient?functionName=getMarketTurnover"]      # NSE breaks it
    rep = reg.refresh()
    assert rep["broken"] == ["api:NextApi/apiClient#getMarketTurnover"]
    site.routes["/api/NextApi/apiClient?functionName=getMarketTurnover"] = FakeResp(body={"data": [2]})
    rep = reg.refresh()
    assert rep["recovered"] == ["api:NextApi/apiClient#getMarketTurnover"]


def test_removed_source_after_full_rescan(env):
    site, reg = env
    _base_site(site)
    reg.refresh()
    site.routes["/_next/static/chunks/a.js"] = FakeResp(text='fetch("/api/NextApi/apiClient?functionName=getMarketTurnover")')
    rep = reg.refresh(rescan_all=True)
    assert "api:NextApi/apiClient/indexTrackerApi#getAdvanceDecline" in rep["removed_sources"]
    assert all(s["key"] != "api:NextApi/apiClient/indexTrackerApi#getAdvanceDecline" for s in reg.sources())


def test_fetch_template_requires_params_and_fills_them(env):
    site, reg = env
    _base_site(site)
    reg.refresh()
    key = "api:NextApi/apiClient/indexTrackerApi#getAdvanceDecline"
    with pytest.raises(NSEDataError):
        reg.fetch(key)
    site.routes["/api/NextApi/apiClient/indexTrackerApi?functionName=getAdvanceDecline&index=NIFTY%2050"] = FakeResp(body={"ok": 1})
    assert reg.fetch(key, index="NIFTY 50") == {"ok": 1}


def test_archive_dated_files_collapse_and_probe_walks_back(env):
    from datetime import date, timedelta
    site, reg = env
    _base_site(site)
    site.routes["/_next/static/chunks/a.js"] = FakeResp(text='"/content/nsccl/fao_participant_oi_07112026.csv"')
    # file exists only for D-2
    d = date.today() - timedelta(days=2)
    site.routes[f"/content/nsccl/fao_participant_oi_{d.strftime('%d%m%Y')}.csv"] = FakeResp(content=b"a,b\n1,2\n")
    reg.refresh()
    rec = reg.data["sources"]["archive:/content/nsccl/fao_participant_oi_{date}.csv"]
    assert rec["probe"]["status"] == "ok" and rec["probe"]["days_back"] == 2


def test_nothing_reachable_leaves_registry_untouched(env):
    site, reg = env
    _base_site(site); reg.refresh()
    before = json.dumps(reg.data["sources"], sort_keys=True)
    site.routes.clear()
    with pytest.raises(NSEDataError):
        reg.refresh()
    assert json.dumps(reg.data["sources"], sort_keys=True) == before


def test_registry_persists_across_instances(env, tmp_path):
    site, reg = env
    _base_site(site); reg.refresh()
    again = SourceRegistry(path=tmp_path / "sources.json")
    assert again.pages() == reg.pages() and len(again.sources()) == len(reg.sources())


def test_refresh_if_stale_only_when_old_and_throttled(env, monkeypatch):
    from datetime import datetime, timedelta, timezone
    site, reg = env
    _base_site(site)
    monkeypatch.setenv("NSELIB_AUTO_REFRESH", "1")
    assert reg.refresh_if_stale(background=False) is True          # never crawled -> stale
    assert reg.data["updated"]
    assert reg.refresh_if_stale(background=False) is False         # fresh now
    reg.data["updated"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert reg.refresh_if_stale(background=False) is False         # stale but lock <10 min old
    monkeypatch.setenv("NSELIB_AUTO_REFRESH", "0")
    reg._path.with_suffix(".lock").unlink()
    assert reg.refresh_if_stale(background=False) is False         # opted out
