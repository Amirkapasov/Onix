# Лицензии и атрибуция данных

Публичная выгрузка `data/pois_open.json` собрана автоматически командой `python pipeline/run_all.py`
только из открытых источников:

- **OpenStreetMap** — © участники OpenStreetMap, лицензия **ODbL 1.0**
  (https://www.openstreetmap.org/copyright, https://opendatacommons.org/licenses/odbl/1-0/).
  `data/pois_open.json` — производная база данных OSM и распространяется на условиях ODbL 1.0
  (атрибуция и share-alike). Данные получены через Overpass API или выгрузку Geofabrik.
- **Wikidata** — **CC0 1.0** (https://creativecommons.org/publicdomain/zero/1.0/).
- **Википедия** — тексты описаний (первые 1–3 предложения вводной части статей ruwiki) по лицензии
  **CC BY-SA 4.0** (https://creativecommons.org/licenses/by-sa/4.0/); ссылка на статью — в поле `sources` каждого объекта.
- **Wikimedia Commons** — фото мест (поле `image`) и `data/category_photos.json` (фолбэк по категориям и обложка).
  Файлы не копируются, хранятся только ссылки. Берутся лишь CC0, Public domain, CC BY и CC BY-SA; у каждого
  фото указаны автор, лицензия и страница файла (`page_url`) — при показе подписывать «Фото: автор, лицензия».

## Данные 2GIS в репозиторий не входят

Часы работы, рейтинги, контакты и места из **2GIS Places API** используются только в полной базе
`data/pois.json`, которая не публикуется (условия использования API 2GIS для демо-ключа не разрешают
распространять полученные данные). Полную базу можно воспроизвести самостоятельно:

```bash
cp .env.example .env              # указать собственный TWOGIS_API_KEY (platform.2gis.ru)
python pipeline/run_all.py        # → data/pois.json (полная) и data/pois_open.json (открытая)
```

Без ключа 2GIS шаг тихо пропускается, и обе базы содержат только открытые данные.
