import type {Feature, Geometry} from 'geojson';

export type Scene = Feature<Geometry, {datetime?: string; 'eo:cloud_cover'?: number; 'rslib:synthetic'?: boolean}> & {id: string; collection: string};
export type BBox = [number,number,number,number];
export type Surface = {bbox:BBox;elevation_url:string;manifest_url:string;source:string;source_valid_fraction:number};
export type Stats = {valid_fraction: number; mean: number|null; p05: number|null; median: number|null; p95: number|null; valid_pixels: number; total_pixels: number};
export type Run = {id: string; synthetic: boolean; preview_url: string; cog_url: string; report_url: string; manifest_url: string; elapsed_seconds: number; statistics: Stats | Record<string,Stats>; sampling: string; mask: {clear_fraction: number}};
