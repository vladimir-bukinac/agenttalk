# Comprehension on Python: the trial's result

Status: spike, never merged. Branch `spike/comprehension-python`, built on the reviewed design (`docs/design/comprehension-python.md` at `36f5e783`). Run on 2026-10-14, read-only, on Satchmo 0.9.2 (the PyPI source package, Python 2) and on Shuup 3.1.0 (the `upstream` tag of the practice copy, Python 3). It took about two hours of the two-day limit. Nothing was cut.

**In plain words:** the trial asked whether agenttalk's inventory could understand Python code, and whether Java fits the proposed shared format without loss. Both questions that would have stopped the work passed. Every Python file could be read: Satchmo 491 of 492 fully, Shuup all 1,638, with identical results on Python 3.10 and 3.14. Java's results come back unchanged after a trip through the shared format, for every Java result the existing tests produce: 516 distinct results, on Python 3.10 and 3.14. Imports resolve almost completely. Routes are found wherever they are written down, but a large part of both shops' web addresses is assembled while the site runs, and a static reading can only name those places, not list the addresses. The trial also found seven things the design got wrong; they are at the end.

## What it found

| | Satchmo 0.9.2 | Shuup 3.1.0 |
|---|---|---|
| Python files (modules) | 492 (105 packages) | 1,638 (234 packages) |
| How they were read | 443 as they are; 48 after Python 2 repairs; 1 as an outline only | 1,638 as they are |
| Python 2 repairs applied | `except X, e:` 24, print statements 20, `raise X, msg` 7, `<>` 5, `L` suffix 1 (in files) | none |
| Classes; module-level functions | 553; 510 | 2,188; 3,078 |
| Imports inside the code base, resolved | 1,007 (118 of them Python 2 sibling imports) | 8,859 (721 relative) |
| Imports to the standard library; to other libraries | 451; 1,209 | 1,348; 4,114 |
| Imports not resolved | 0 | 1 (a dead import in Shuup itself), 7 ambiguous by suffix |
| Django models | 95: 91 direct, 4 through a model in the scan | 97 certain: 55 direct, 42 through a model in the scan; 53 more inherit from third-party bases (translation, polymorphic) that may be models |
| Web routes, composed from the root URL file | 60 | 25 distinct (reached from two root files) |
| Web routes found but not reachable statically | 64: payment-module URLs chosen from settings at run time, and extension URLs attached by `collect_urls` signal listeners | 50: front apps loaded through Shuup's `provides` registry, test URL files |
| Views behind the routes | 108 functions found, 15 in Django itself, 1 not found | 61 classes, 27 functions, 10 in other libraries, 1 not static |
| Entry points | 10 management commands, 14 `__main__` starts, 18 middleware entries | 11 management commands, 11 `__main__` starts, 24 middleware entries |
| Recognised but not modelled (counted, not dropped) | admin registrations 52, signal receivers 46, template tags 14 | admin route helper `admin_url` 144, signal receivers 91, `AppConfig.ready` 14, WSGI 1 |
| Dynamic imports it could not follow | 6 | 7 |

Shuup's admin pages, most of its URL map, are built in code through `admin_url(...)` inside admin modules. The trial lists them as 144 unmodelled entries; it does not turn them into routes.

## How the pass marks came out

| # | Question | Result |
|---|---|---|
| S1 | Can every file be read? | **Pass.** Satchmo 99.8% read fully on 3.10 and 3.14, none unreadable; Shuup 100%. The claims are identical on 3.10 and 3.14 except the interpreter field (digests `1f010580` and `996d50d2`). The first 3.10 run failed this for 5 Satchmo files: see design error 1 |
| S2 | Do imports resolve? | **Pass.** Using the design's oracle: Satchmo 1,005 of 1,005, Shuup 8,546 of 8,547 (the miss is Shuup's own dead import). Hand check: 40 of 40 correct. 314 correct resolutions fall outside the oracle list (design error 6) |
| S3 | Are routes found? | **Pass after one fix.** 10 of 10 URL modules match a hand count; on the first run Shuup's front URLs gave 23 of 24 (design error 3) |
| S4 | Does Java fit without loss? | **Pass.** Run inside all 1,518 comprehension tests (1,508 passed, 10 skipped, as without the check), on 3.10 and 3.14: 516 distinct Java results, checked 3,742 times at three boundaries, all came back exactly. Two deliberately broken converters were caught (205 and 7 failures) |
| S5 | What does it cost? | Satchmo: 4.2 s (3.10) and 4.5 s (3.14). Shuup: 20.8 s (3.10) and 16.9 s (3.14), about 40% of it in the Python 2 marker scan. Claims: 1.5 MB and 5.9 MB of JSON |
| S6 | How noisy are by-name strings? | **Too noisy as designed:** 7 of 20 (Satchmo) and 8 of 20 (Shuup) are real references. Most of the noise is Django model labels such as `shuup.Shop` |

## What the design got wrong

1. **The token stream itself differs between Pythons.** Python 3.10 splits `<>` into two tokens; 3.14 gives one. The Python 2 detector must recognise both, or 3.10 misses Python 2 files. The interpreter check of S1 caught this.
2. **Settings and include strings are relative to the project folder.** Satchmo's `ROOT_URLCONF = 'simple.urls'` names a module that the package chain calls `satchmo.projects.simple.urls`, because `manage.py` puts the project folder on the path. The suffix rule the design gives imports is needed for these strings too.
3. **URL lists are built in branches and rebuilt at run time.** Satchmo assigns `urlpatterns` inside `if`/`else`; Shuup reassigns it as `list(chain(<plugins>, urlpatterns, [index], <plugins>))`. The reader has to read module-level branches, keep the earlier list, and read lists nested inside such a call.
4. **Views are wrapped.** `login_required(View.as_view())` and `csrf_exempt(...)` hide the view; before unwrapping, 50 Shuup routes had no view.
5. **The general by-name rule should be dropped.** Instead, recognise three more slots: model labels (`to="app.Model"`, South's `orm['app.model']`) as references to models, `module:Name` strings (Shuup's `provides`), and named settings.
6. **The S2 oracle was too narrow.** "Shuup: `shuup`" leaves out `shuup_tests` and the helper scripts; the oracle should list every top-level package in the repository.
7. **Models through third-party bases cannot be decided** from inheritance alone (53 Shuup classes). A report needs a short list of known model bases, or must say "unknown". Also not in the design: `__main__.py` files and `setup.py`'s `scripts=` are entry points too, and many app-level `settings.py` files are not Django settings.

Also found: Shuup 3.1.0 imports `shuup.shop.views.activation_views` in `shuup/front/views/order.py` line 40, and that module does not exist. A static reading catches dead imports like this.

Technical details: `README.md` (how to run), `output/` (summaries per codebase and interpreter, routes, samples, the round-trip report, `handchecks.md`). The full claims files stay in the builder's scratch folder.
