# satfinder-katalog

Pro SatFinder uygulamasının kataloğu. `catalog.json` her pazartesi otomatik üretilir.

- Uydu konumları: CelesTrak geostasyoner yörünge verisi (yaklaşık ±0,1°). Aktiflik bu veriden anlaşılmaz.
- `enrich.csv`: elle doğrulanan operatör ve aktiflik. VERIFIED_ACTIVE veya INACTIVE için `verified_on` (YYYY-AA-GG) ve `source` zorunludur. 365 günden eski doğrulama geçersiz sayılır.
- `transponders.csv`: elle doğrulanan frekanslar. `source` ve `checked_on` zorunludur. Bilinmeyen alan boş bırakılır.
- Hatalı satır varsa üretim durur ve eski `catalog.json` korunur.
