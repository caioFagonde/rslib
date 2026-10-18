# Source registry and attribution

Catalogs, acquisition dates, processing versions and collection membership change. The interfaces request live collection metadata instead of treating a static source list as a guarantee of availability.

| Source | Access and interpretation |
| --- | --- |
| [Earth Search](https://github.com/Element84/earth-search) | STAC Item Search; unsigned public COGs where available. Prefer `sentinel-2-c1-l2a` for calibrated Sentinel-2 analysis. Some other assets may require requester-pays credentials. |
| [Planetary Computer](https://planetarycomputer.microsoft.com/catalog) | STAC discovery with short-lived asset signing; collection licensing still applies. |
| [AWS Sentinel-2](https://registry.opendata.aws/sentinel-2-l2a-cogs/) | Copernicus Sentinel / ESA observations, processed/hosted by the named providers. Retain collection license and processing provenance. |
| [Copernicus DEM](https://registry.opendata.aws/copernicus-dem/) | Surface elevation, including vegetation/infrastructure; GLO-30 public coverage has exceptions. Verify EGM2008 vertical reference and tile license before combining with other elevation sources. |
| [Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) | Visualization terrain in Terrarium RGB encoding. [Mapzen/Tilezen source attribution](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) applies. Do not assume these web tiles are interchangeable with an analytical bare-earth DEM. |
| [SoilGrids](https://docs.isric.org/globaldata/soilgrids/) | 250 m predictions, depth-specific properties and marginal uncertainty; ISRIC, CC BY 4.0. Cite Poggio et al. 2021 and retain units/depth/statistic. |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | Basemap attribution is displayed on the map. Public raster tiles are used only for visible interactive views, with bounded request concurrency. For sustained traffic, configure an appropriate hosted or self-hosted tile service. |

Standards and primary references:

- [STAC Item/Catalog/Collection](https://stacspec.org/en/about/stac-spec/) and [STAC API 1.0](https://api.stacspec.org/v1.0.0/).
- [GDAL COG driver](https://gdal.org/en/stable/drivers/raster/cog.html).
- [deck.gl TerrainLayer](https://deck.gl/docs/api-reference/geo-layers/terrain-layer), [DataFilterExtension](https://deck.gl/docs/api-reference/extensions/data-filter-extension) and [Turf area](https://turfjs.org/docs/api/area).
- [USGS TRIGRS report and equations](https://pubs.usgs.gov/of/2008/1159/), [Saxton–Rawls pedotransfer](https://doi.org/10.2136/sssaj2005.0117).
- [scikit-learn grouped validation](https://scikit-learn.org/stable/modules/cross_validation.html).

The initial fixture has three timestamps pointing to the same synthetic rasters. It is an interface/acquisition substitute and not an observed vegetation trend. Generated concept artwork is illustrative and separate from operational screenshots. Dataset names that appear in concept art do not establish an implemented connector or license grant.
