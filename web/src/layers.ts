/** Reusable deck.gl layer factories for applications built on the shared analysis API. */
import {BitmapLayer, GeoJsonLayer, PointCloudLayer, ScatterplotLayer} from '@deck.gl/layers';
import {MVTLayer, TerrainLayer, Tile3DLayer, TileLayer} from '@deck.gl/geo-layers';
import {ContourLayer, HeatmapLayer, HexagonLayer} from '@deck.gl/aggregation-layers';
import {DataFilterExtension, _TerrainExtension as TerrainExtension, type DataFilterExtensionProps} from '@deck.gl/extensions';
import type {FeatureCollection} from 'geojson';
import type {BBox, Scene} from './types';
import terrainWorkerUrl from '@loaders.gl/terrain/terrain-worker.js?url';

const filter = new DataFilterExtension({filterSize: 1});
export const terrainAttribution = 'Terrain: Mapzen / Tilezen; source attribution in Sources panel';

async function retryFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  let failure: unknown;
  for(let attempt=0;attempt<3;attempt++) {
    try {
      const response=await fetch(input,init);
      if(response.ok || response.status<500 && response.status!==429)return response;
      failure=new Error(`Tile service returned ${response.status}`);
    } catch(error) {if(init?.signal?.aborted)throw error;failure=error;}
    await new Promise(resolve=>setTimeout(resolve,200*2**attempt));
  }
  throw failure;
}

export function basemap(visible = true) {
  return new TileLayer<ImageBitmap>({id:'basemap', data:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    visible, minZoom:0, maxZoom:19, tileSize:256, maxRequests:6,loadOptions:{fetch:retryFetch},
    renderSubLayers: props => {
      const {west,south,east,north} = {
          west: props.tile.boundingBox[0][0], south: props.tile.boundingBox[0][1],
          east: props.tile.boundingBox[1][0], north: props.tile.boundingBox[1][1]};
      return new BitmapLayer({id:`${props.id}-bitmap`, image:props.data, bounds:[west,south,east,north]});
    },
  });
}

export function footprints(scenes: Scene[], maxCloud: number, selected: string|undefined, select: (scene:Scene)=>void) {
  return new GeoJsonLayer<{ 'eo:cloud_cover'?: number }, DataFilterExtensionProps<Scene>>({id:'footprints',
    data: {type:'FeatureCollection',features:scenes} as FeatureCollection,
    stroked:true,filled:false,pickable:true,lineWidthMinPixels:1,
    getFillColor: f => f.id === selected ? [122,218,162,28] : [202,225,207,10],
    getLineColor: f => f.id === selected ? [130,237,169,235] : [184,213,193,110],
    getFilterValue: f => f.properties['eo:cloud_cover'] ?? 101,
    filterRange:[0,maxCloud],extensions:[filter],
    updateTriggers:{getFillColor:[selected],getLineColor:[selected]},
    onClick: info => {if(info.object) select(info.object as Scene);},
  });
}

export function analysisBitmap(url:string, bounds:BBox, opacity:number, drape:boolean) {
  return new BitmapLayer({id:'analysis',image:url,bounds,opacity,
    ...(drape ? {extensions:[new TerrainExtension()],terrainDrawMode:'drape'} : {})});
}

export function terrain(visible:boolean) {
  return new TerrainLayer({id:'terrain',visible,
    elevationData:'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png',
    texture:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    elevationDecoder:{rScaler:256,gScaler:1,bScaler:1/256,offset:-32768},
    minZoom:0,maxZoom:13,meshMaxError:8,tileSize:256,maxRequests:4,loadOptions:{fetch:retryFetch,terrain:{workerUrl:terrainWorkerUrl}},
    operation:'terrain+draw',material:{ambient:.5,diffuse:.6,shininess:10},
  });
}

export function surfaceTerrain(elevationUrl:string,textureUrl:string,bounds:BBox,opacity:number) {
  return new TerrainLayer({id:'analysis-terrain',elevationData:elevationUrl,texture:textureUrl,bounds,
    elevationDecoder:{rScaler:256,gScaler:1,bScaler:1/256,offset:-32768},meshMaxError:4,
    opacity,material:{ambient:.8,diffuse:.35,shininess:2},loadOptions:{fetch:retryFetch,terrain:{workerUrl:terrainWorkerUrl}}});
}

// Additional application-layer entry points, using deck.gl's typed properties.
export const layerCatalog = {
  geojson: GeoJsonLayer, raster: BitmapLayer, tiles: TileLayer, terrain: TerrainLayer,
  vectorTiles: MVTLayer, tiles3d: Tile3DLayer, pointCloud: PointCloudLayer,
  points: ScatterplotLayer, heatmap: HeatmapLayer, hexagons: HexagonLayer, contours: ContourLayer,
};
