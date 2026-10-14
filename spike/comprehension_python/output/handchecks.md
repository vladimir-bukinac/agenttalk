# Hand checks (spike questions S2, S3 and S6)

Done on 2026-10-14 against the Python 3.14 run. Samples were drawn with `random.Random(495)` in `run_spike.py`.
Each check compared the reader's answer with the file itself.

## S2: 20 random resolved imports per codebase

The sample rows are in `s2-sample-<codebase>-py3.14.json` (file, line, written target, resolved module, rule).

- **Satchmo:** 20 of 20 correct. Two of them are Python 2 sibling imports (`import signals` in `product/tests.py` resolves to `product/signals.py`; `import views` in `satchmo_ext/upsell/__init__.py` resolves to `satchmo_ext/upsell/views.py`). `from payment.views import confirm, payship` correctly resolves to the modules `payment/views/confirm.py` and `payment/views/payship.py`.
- **Shuup:** 20 of 20 correct, including relative imports such as `from .list import UserListView` resolving to `shuup/admin/modules/users/views/list.py`.

**Outside the oracle but resolved in the scan:**
- Satchmo has 1: `setup.py` imports `ez_setup`, a script beside it.
- Shuup has 313: `shuup_tests` (301), `sanity_utils` (10, helper scripts in `_misc/`), `shuup_setup_utils` (1) and `shuup_introspection_helper` (1).

All 314 are correct resolutions. The oracle list the design names ("Shuup: `shuup`") leaves out the repository's other top-level packages.

**Inside the oracle and not resolved:** Shuup has 1. `shuup/front/views/order.py` line 40 imports `shuup.shop.views.activation_views`, a module that does not exist in Shuup 3.1.0. The import sits inside a rarely taken branch of a view method, so it is a dead import in Shuup itself, not a resolver miss.

## S3: five URL modules per codebase, counted by hand

| Module | Reader | By hand |
|---|---|---|
| `payment.modules.authorizenet.urls` | 3 | 3 |
| `payment.modules.sagepay.urls` | 4 | 4 |
| `payment.modules.sermepa.urls` | 6 | 6 |
| `product.urls` (2 entries whose patterns are built from settings) | 2 | 2 |
| `product.urls.products` (two `patterns()` calls joined with `+=`) | 5 | 5 |
| `shuup.front.apps.auth.urls` | 6 | 6 |
| `shuup.front.urls` | 24 (23 on the first run) | 24 |
| `shuup.testing.single_page_checkout_test_urls` | 5 | 5 |
| `shuup.xtheme.urls` (one pattern is a `"""...""".strip()` call, kept as a computed pattern) | 7 | 7 |
| `shuup_workbench.test_urls` | 3 | 3 |

On the first run, `shuup.front.urls` gave 23. The 24th entry, the index route `^$`, sits inside the later reassignment `urlpatterns = list(chain(<provides>, urlpatterns, [url(r"^$", ...)], <provides>))`. The reader was changed to read URL lists nested inside such a reassignment, and the count is now 24.

## S6: 20 random by-name strings per codebase

A by-name string is a string outside the recognised slots that is exactly a dotted name, or `module:Name`, and that names a module in the scan.

**Satchmo: 7 of 20 are real references to code.**
- Real:
  - South migration field classes such as `satchmo_utils.fields.CurrencyField` (4);
  - modules chosen through a setting: `tax.modules.us_sst` and `shipping.modules.per` (2);
  - `satchmo_utils.thumbnail.field.ImageWithThumbnailField` (1).
- Noise:
  - 11 Django or South model labels (`product.option`, `product.Product` and similar), which name a model by app label, not a module path;
  - 2 logger names (`l10n.utils`, `satchmo_utils.thumbnail`).

**Shuup: 8 of 20 are real.**
- Real:
  - `provides` entries such as `shuup.importer.admin_module:ImportAdminModule` (4);
  - a task name for `run_task`;
  - an `admin_url` view string;
  - a settings value `shuup.testing.shop_provider.TestingAdminShopProvider`;
  - a provides list entry.
- Noise:
  - 9 model labels (`shuup.Shop`, `shuup.Contact`, `shuup.product` and similar);
  - 3 `INSTALLED_APPS` membership checks in tests.

Across all by-name strings, two-part "app.model" labels that are not modules make up 435 of 747 (Satchmo) and 854 of 1,770 (Shuup).
