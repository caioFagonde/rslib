import { Deck, MapView, WebMercatorViewport, type Layer } from "@deck.gl/core";
import {
  BitmapLayer,
  GeoJsonLayer,
  ScatterplotLayer,
  TextLayer,
} from "@deck.gl/layers";
import { TileLayer } from "@deck.gl/geo-layers";
import type {
  Feature,
  FeatureCollection,
  Polygon,
  MultiPolygon,
  Position,
} from "geojson";

export type Boundary = {
  id: string;
  name: string;
  geometry: Polygon | MultiPolygon;
};
export type Bounds = [number, number, number, number];
type Options = {
  bounds: Bounds;
  fields: Boundary[];
  selected?: string;
  image?: string;
  imageBounds?: Bounds;
  opacity: number;
  base: boolean;
  inspectCells?: boolean;
  point?: [number, number];
};

export class OpticalMap {
  private deck: Deck<MapView>;
  private view = {
    longitude: -44.65,
    latitude: -22.4,
    zoom: 13,
    pitch: 0,
    bearing: 0,
  };
  private options: Options;
  private vertices: Position[] = [];
  private drawing = false;
  constructor(
    private element: HTMLDivElement,
    private onPoint: (lon: number, lat: number) => void,
    private onField: (id: string) => void,
    private onMessage: (text: string) => void,
  ) {
    this.options = {
      bounds: [-44.66, -22.41, -44.64, -22.39],
      fields: [],
      opacity: 0.8,
      base: true,
    };
    this.deck = new Deck<MapView>({
      parent: element,
      views: new MapView({ id: "optical" }),
      initialViewState: this.view,
      controller: { doubleClickZoom: false },
      onViewStateChange: ({ viewState }) => {
        this.view = { ...this.view, ...viewState };
      },
      onClick: (info) => {
        this.click(info.coordinate);
      },
      getCursor: ({ isDragging }) =>
        this.drawing ? "crosshair" : isDragging ? "grabbing" : "crosshair",
      getTooltip: (info) =>
        info.object?.properties?.name
          ? { text: info.object.properties.name }
          : null,
      onError: () =>
        onMessage(
          "A map resource could not load. Analysis and raster comparisons remain available.",
        ),
    });
    this.fit(this.options.bounds);
    this.layers();
  }
  private click(coordinate?: number[]) {
    if (!coordinate) return;
    const [lon, lat] = coordinate;
    if (this.drawing) {
      if (this.vertices.length >= 100) {
        this.onMessage("Polygon drawing is limited to 100 vertices. Import GeoJSON for larger boundaries.");
        return;
      }
      this.vertices.push([lon, lat]);
      this.layers();
      this.onMessage(`${this.vertices.length} vertices · finish the polygon or press Escape to cancel.`);
    } else this.onPoint(lon, lat);
  }
  update(options: Options) {
    this.options = options;
    this.layers();
  }
  fit(bounds: Bounds) {
    const fitted = new WebMercatorViewport({
      width: this.element.clientWidth || 700,
      height: this.element.clientHeight || 460,
    }).fitBounds(
      [
        [bounds[0], bounds[1]],
        [bounds[2], bounds[3]],
      ],
      { padding: 55 },
    );
    this.view = {
      ...this.view,
      longitude: fitted.longitude,
      latitude: fitted.latitude,
      zoom: Math.min(18, fitted.zoom),
    };
    this.deck.setProps({ initialViewState: this.view });
  }
  startDrawing() {
    this.vertices = [];
    this.drawing = true;
    this.layers();
    this.onMessage(
      "Click polygon vertices on the map, then choose Finish polygon.",
    );
  }
  cancelDrawing() {
    this.drawing = false;
    this.vertices = [];
    this.layers();
    this.onMessage("Polygon drawing cancelled.");
  }
  finishDrawing(): Polygon | undefined {
    if (this.vertices.length < 3) {
      this.onMessage("Add at least three vertices.");
      return;
    }
    const geometry: Polygon = {
      type: "Polygon",
      coordinates: [[...this.vertices, this.vertices[0]]],
    };
    this.drawing = false;
    this.vertices = [];
    this.layers();
    return geometry;
  }
  private layers() {
    const o = this.options,
      [w, s, e, n] = o.bounds;
    const area: Feature<Polygon> = {
      type: "Feature",
      properties: {},
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [w, s],
            [e, s],
            [e, n],
            [w, n],
            [w, s],
          ],
        ],
      },
    };
    const fields: FeatureCollection<Polygon | MultiPolygon> = {
      type: "FeatureCollection",
      features: o.fields.map((f) => ({
        type: "Feature",
        id: f.id,
        properties: { id: f.id, name: f.name },
        geometry: f.geometry,
      })),
    };
    const layers: Layer[] = [
      new TileLayer<ImageBitmap>({
        id: "optical-base",
        data: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        visible: o.base,
        minZoom: 0,
        maxZoom: 19,
        tileSize: 256,
        maxRequests: 4,
        renderSubLayers: (props) =>
          new BitmapLayer({
            id: props.id + "-image",
            image: props.data,
            bounds: [
              props.tile.boundingBox[0][0],
              props.tile.boundingBox[0][1],
              props.tile.boundingBox[1][0],
              props.tile.boundingBox[1][1],
            ],
            desaturate: 1,
          }),
      }),
    ];
    if (o.image && o.imageBounds)
      layers.push(
        new BitmapLayer({
          id: "optical-data",
          image: o.image,
          bounds: o.imageBounds,
          _imageCoordinateSystem: "cartesian",
          opacity: o.opacity,
          textureParameters: { minFilter: "nearest", magFilter: "nearest" },
        }),
      );
    layers.push(
      new GeoJsonLayer({
        id: "optical-aoi",
        data: area,
        filled: false,
        getLineColor: [40, 74, 98, 200],
        lineWidthMinPixels: 1,
      }),
    );
    layers.push(
      new GeoJsonLayer({
        id: "optical-fields",
        data: fields,
        pickable: !this.drawing && !o.inspectCells,
        filled: true,
        getFillColor: (f) =>
          f.id === o.selected ? [252, 196, 80, 30] : [255, 255, 255, 4],
        getLineColor: (f) =>
          f.id === o.selected ? [255, 184, 50, 255] : [247, 242, 225, 245],
        lineWidthMinPixels: 2,
        updateTriggers: {
          getFillColor: [o.selected],
          getLineColor: [o.selected],
        },
        onClick: (info) => {
          // Picking can use the previous GPU frame immediately after a mode
          // switch. Honor the current interaction mode even in that interval.
          if (this.drawing || this.options.inspectCells) {
            this.click(info.coordinate);
            return true;
          }
          if (info.object) {
            this.onField(String(info.object.id));
            return true;
          }
          return false;
        },
      }),
    );
    const labels = o.fields.map((f) => {
      const ring =
        f.geometry.type === "Polygon"
          ? f.geometry.coordinates[0]
          : f.geometry.coordinates[0][0];
      const xs = ring.map((p) => p[0]),
        ys = ring.map((p) => p[1]);
      return {
        name: f.name,
        position: [
          (Math.min(...xs) + Math.max(...xs)) / 2,
          (Math.min(...ys) + Math.max(...ys)) / 2,
        ] as [number, number],
      };
    });
    layers.push(
      new TextLayer({
        id: "optical-labels",
        data: labels,
        getPosition: (d) => d.position,
        getText: (d) => d.name,
        getSize: 12,
        getColor: [255, 255, 255, 255],
        background: true,
        getBackgroundColor: [25, 44, 56, 210],
        backgroundPadding: [5, 3],
        fontFamily: "system-ui",
        fontWeight: 600,
      }),
    );
    if (o.point)
      layers.push(
        new ScatterplotLayer({
          id: "optical-point",
          data: [o.point],
          getPosition: (d) => d,
          getRadius: 5,
          radiusUnits: "pixels",
          filled: false,
          stroked: true,
          getLineColor: [255, 255, 255, 255],
          lineWidthMinPixels: 2,
        }),
      );
    if (this.vertices.length) {
      layers.push(
        new ScatterplotLayer({
          id: "draw-vertices",
          data: this.vertices,
          getPosition: (d) => d,
          getRadius: 4,
          radiusUnits: "pixels",
          getFillColor: [255, 184, 50, 255],
        }),
      );
      if (this.vertices.length > 1)
        layers.push(
          new GeoJsonLayer({
            id: "draw-edge",
            data: {
              type: "Feature",
              properties: {},
              geometry: { type: "LineString", coordinates: this.vertices },
            },
            getLineColor: [255, 184, 50, 255],
            lineWidthMinPixels: 2,
          }),
        );
    }
    this.deck.setProps({ layers });
  }
}
