type Palette = {
  background: string;
  surface: string;
  primary: string;
  secondary: string;
  accent: string;
  dark: string;
  border: string;
};

type Point = {
  x: number;
  y: number;
};

type QuarterTurn = 0 | 1 | 2 | 3;

export type RenderShape =
  | {
      kind: "rect";
      x: number;
      y: number;
      width: number;
      height: number;
      fill: string;
      rx?: number;
    }
  | {
      kind: "circle";
      cx: number;
      cy: number;
      r: number;
      fill: string;
    }
  | {
      kind: "polygon";
      points: string;
      fill: string;
      seamSafe?: boolean;
    }
  | {
      kind: "path";
      d: string;
      fill: string;
    };

type TileRendererArgs = {
  origin: Point;
  size: number;
  rotation: QuarterTurn;
  palette: Palette;
};

type TileRenderer = (args: TileRendererArgs) => RenderShape[];

type CellPlacement = {
  row: number;
  col: number;
  rotation: QuarterTurn;
};

export const GRID_SIZE = 4;
export const CELL_SIZE = 24;
export const VIEWBOX_SIZE = GRID_SIZE * CELL_SIZE;
export const CENTER = VIEWBOX_SIZE / 2;
export const RADIUS = VIEWBOX_SIZE / 2;

/**
 * Bleed для прямоугольников фона клетки.
 */
const CELL_BLEED = 0.45;

/**
 * Отдельный bleed для полигонов, которые касаются границы клетки.
 * Нужен, чтобы убрать hairline seams без stroke.
 */
const POLYGON_EDGE_BLEED = 1;

const CORNER_CELLS: readonly CellPlacement[] = [
  { row: 0, col: 0, rotation: 0 },
  { row: 0, col: 3, rotation: 1 },
  { row: 3, col: 3, rotation: 2 },
  { row: 3, col: 0, rotation: 3 },
] as const;

const HORIZONTAL_EDGE_CELLS: readonly CellPlacement[] = [
  { row: 0, col: 1, rotation: 0 },
  { row: 0, col: 2, rotation: 1 },
  { row: 3, col: 2, rotation: 2 },
  { row: 3, col: 1, rotation: 3 },
] as const;

const VERTICAL_EDGE_CELLS: readonly CellPlacement[] = [
  { row: 1, col: 0, rotation: 0 },
  { row: 1, col: 3, rotation: 1 },
  { row: 2, col: 3, rotation: 2 },
  { row: 2, col: 0, rotation: 3 },
] as const;

const CENTER_CELLS: readonly CellPlacement[] = [
  { row: 1, col: 1, rotation: 0 },
  { row: 1, col: 2, rotation: 1 },
  { row: 2, col: 2, rotation: 2 },
  { row: 2, col: 1, rotation: 3 },
] as const;

/**
 * Назначение функции: Выполняет операцию `polygonPointsToPath` для объекта «результат операции `polygonPointsToPath`». Возвращает результаты выражений: `""`; ```M ${normalized.replace(/ /g, " L ")} Z```.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function polygonPointsToPath(points: string) {
  const normalized = points.trim().replace(/\s+/g, " ");

  if (!normalized) {
    return "";
  }

  return `M ${normalized.replace(/ /g, " L ")} Z`;
}

/**
 * Назначение функции: Объединяет данные объекта «результат операции `mergeSeamSafePolygons`»; операция `mergeSeamSafePolygons`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function mergeSeamSafePolygons(shapes: RenderShape[]): RenderShape[] {
  const merged: RenderShape[] = [];

  let activeFill: string | null = null;
  let activePath = "";

  /**
   * Назначение функции: Выполняет операцию `flush` для объекта «значение типа `mergeSeamSafePolygons`». Выполняет вызовы: `merged.push`, `activePath.trim`; значение не возвращает.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const flush = () => {
    if (activeFill && activePath) {
      merged.push({
        kind: "path",
        d: activePath.trim(),
        fill: activeFill,
      });
    }

    activeFill = null;
    activePath = "";
  };

  for (const shape of shapes) {
    if (shape.kind === "polygon" && shape.seamSafe) {
      const pathPart = polygonPointsToPath(shape.points);

      if (!pathPart) {
        continue;
      }

      if (activeFill === shape.fill) {
        activePath += ` ${pathPart}`;
      } else {
        flush();
        activeFill = shape.fill;
        activePath = pathPart;
      }

      continue;
    }

    flush();
    merged.push(shape);
  }

  flush();

  return merged;
}

/**
 * Назначение функции: Вычисляет хеш данные объекта «хеш»; операция `hashString`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function hashString(input: string): number {
  let h = 2166136261;

  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }

  return h >>> 0;
}

/**
 * Назначение функции: Выполняет операцию `cellOrigin` для объекта «результат операции `cellOrigin`»; возвращает `Point`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function cellOrigin(row: number, col: number): Point {
  return {
    x: col * CELL_SIZE,
    y: row * CELL_SIZE,
  };
}

/**
 * Назначение функции: Выполняет операцию `pointsToString` для объекта «результат операции `pointsToString`». Возвращает результаты выражений: ``points.map((point) => `${point.x},${point.y}`).join(" ")``.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function pointsToString(points: Point[]) {
  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

/**
 * Назначение функции: Выполняет операцию `rotateLocalPoint` для объекта «результат операции `rotateLocalPoint`»; возвращает `Point`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function rotateLocalPoint(
  point: Point,
  size: number,
  rotation: QuarterTurn
): Point {
  switch (rotation) {
    case 0:
      return { x: point.x, y: point.y };
    case 1:
      return { x: size - point.y, y: point.x };
    case 2:
      return { x: size - point.x, y: size - point.y };
    case 3:
      return { x: point.y, y: size - point.x };
    default:
      return point;
  }
}

/**
 * Назначение функции: Преобразует данные объекта «карта»; операция `mapLocalPointsToCell`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function mapLocalPointsToCell(
  localPoints: Point[],
  origin: Point,
  size: number,
  rotation: QuarterTurn
): Point[] {
  return localPoints.map((point) => {
    const rotated = rotateLocalPoint(point, size, rotation);

    return {
      x: origin.x + rotated.x,
      y: origin.y + rotated.y,
    };
  });
}

/**
 * Назначение функции: Выполняет операцию `rectShape` для объекта «результат операции `rectShape`»; возвращает `RenderShape`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function rectShape(
  x: number,
  y: number,
  width: number,
  height: number,
  fill: string,
  rx?: number
): RenderShape {
  return {
    kind: "rect",
    x,
    y,
    width,
    height,
    fill,
    rx,
  };
}

/**
 * Назначение функции: Выполняет операцию `circleShape` для объекта «результат операции `circleShape`»; возвращает `RenderShape`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function circleShape(
  cx: number,
  cy: number,
  r: number,
  fill: string
): RenderShape {
  return {
    kind: "circle",
    cx,
    cy,
    r,
    fill,
  };
}

/**
 * Назначение функции: Выполняет операцию `polygonShape` для объекта «результат операции `polygonShape`»; возвращает `RenderShape`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function polygonShape(
  points: Point[],
  fill: string,
  seamSafe = true
): RenderShape {
  return {
    kind: "polygon",
    points: pointsToString(points),
    fill,
    seamSafe,
  };
}

/**
 * Назначение функции: Выполняет операцию `localRectPoints` для объекта «результат операции `localRectPoints`»; возвращает `Point[]`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function localRectPoints(
  x: number,
  y: number,
  width: number,
  height: number
): Point[] {
  return [
    { x, y },
    { x: x + width, y },
    { x: x + width, y: y + height },
    { x, y: y + height },
  ];
}

/**
 * Назначение функции: Выполняет операцию `fullCellRect` для объекта «результат операции `fullCellRect`»; возвращает `RenderShape`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function fullCellRect(
  origin: Point,
  size: number,
  fill: string,
  bleed = CELL_BLEED
): RenderShape {
  return rectShape(
    origin.x - bleed,
    origin.y - bleed,
    size + bleed * 2,
    size + bleed * 2,
    fill
  );
}

/**
 * Назначение функции: Выполняет операцию `bleedCoordToCellEdge` для объекта «ребро дорожного графа». Возвращает результаты выражений: `-bleed`; `size + bleed`; `value`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function bleedCoordToCellEdge(
  value: number,
  size: number,
  bleed = POLYGON_EDGE_BLEED
) {
  if (value === 0) {
    return -bleed;
  }

  if (value === size) {
    return size + bleed;
  }

  return value;
}

/**
 * Назначение функции: Выполняет операцию `bleedLocalPointsToCellEdges` для объекта «ребро дорожного графа»; возвращает `Point[]`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function bleedLocalPointsToCellEdges(
  localPoints: Point[],
  size: number,
  bleed = POLYGON_EDGE_BLEED
): Point[] {
  return localPoints.map((point) => ({
    x: bleedCoordToCellEdge(point.x, size, bleed),
    y: bleedCoordToCellEdge(point.y, size, bleed),
  }));
}

/**
 * Назначение функции: Выполняет операцию `polygonInCell` для объекта «результат операции `polygonInCell`»; возвращает `RenderShape`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function polygonInCell(
  origin: Point,
  size: number,
  localPoints: Point[],
  fill: string,
  rotation: QuarterTurn = 0,
  seamSafe = true
): RenderShape {
  const effectivePoints = seamSafe
    ? bleedLocalPointsToCellEdges(localPoints, size)
    : localPoints;

  return polygonShape(
    mapLocalPointsToCell(effectivePoints, origin, size, rotation),
    fill,
    seamSafe
  );
}

/**
 * Назначение функции: Выполняет операцию `rectPolygonInCell` для объекта «результат операции `rectPolygonInCell`»; возвращает `RenderShape`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function rectPolygonInCell(
  origin: Point,
  size: number,
  x: number,
  y: number,
  width: number,
  height: number,
  fill: string,
  rotation: QuarterTurn = 0
): RenderShape {
  return polygonInCell(
    origin,
    size,
    localRectPoints(x, y, width, height),
    fill,
    rotation,
    true
  );
}

/**
 * Назначение функции: Выполняет операцию `centeredCircleInCell` для объекта «результат операции `centeredCircleInCell`»; возвращает `RenderShape`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function centeredCircleInCell(
  origin: Point,
  size: number,
  fill: string,
  diameterRatio = 0.48
): RenderShape {
  const radius = (size * diameterRatio) / 2;

  return circleShape(origin.x + size / 2, origin.y + size / 2, radius, fill);
}

/**
 * Назначение функции: Выполняет операцию `diamondPoints` для объекта «результат операции `diamondPoints`»; возвращает `Point[]`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function diamondPoints(size: number, inset = 0): Point[] {
  return [
    { x: size / 2, y: inset },
    { x: size - inset, y: size / 2 },
    { x: size / 2, y: size - inset },
    { x: inset, y: size / 2 },
  ];
}

/**
 * Назначение функции: Выполняет операцию `diamondInCell` для объекта «результат операции `diamondInCell`»; возвращает `RenderShape`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function diamondInCell(
  origin: Point,
  size: number,
  fill: string,
  inset = 0,
  rotation: QuarterTurn = 0
): RenderShape {
  return polygonInCell(
    origin,
    size,
    diamondPoints(size, inset),
    fill,
    rotation,
    true
  );
}

/**
 * Назначение функции: Выполняет операцию `cornerCutTrianglePoints` для объекта «результат операции `cornerCutTrianglePoints`»; возвращает `Point[]`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function cornerCutTrianglePoints(size: number, cutRatio = 0.5): Point[] {
  const start = size * (1 - cutRatio);

  return [
    { x: size, y: size },
    { x: size, y: start },
    { x: start, y: size },
  ];
}

/**
 * Назначение функции: Выполняет операцию `topLeftTrianglePoints` для объекта «результат операции `topLeftTrianglePoints`»; возвращает `Point[]`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function topLeftTrianglePoints(size: number): Point[] {
  return [
    { x: 0, y: 0 },
    { x: size, y: 0 },
    { x: 0, y: size },
  ];
}

/**
 * Назначение функции: Выполняет операцию `diagonalBandPoints` для объекта «результат операции `diagonalBandPoints`»; возвращает `Point[]`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function diagonalBandPoints(size: number): Point[] {
  return [
    { x: size, y: size },
    { x: size, y: 0 },
    { x: size * 0.5, y: size },
  ];
}

/**
 * Назначение функции: Выполняет операцию `horizontalBandPoints` для объекта «результат операции `horizontalBandPoints`»; возвращает `Point[]`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function horizontalBandPoints(size: number, thickness = 0.36): Point[] {
  const height = size * thickness;
  const y = (size - height) / 2;

  return localRectPoints(0, y, size, height);
}

/**
 * Назначение функции: Выполняет операцию `verticalBandPoints` для объекта «результат операции `verticalBandPoints`»; возвращает `Point[]`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function verticalBandPoints(size: number, thickness = 0.36): Point[] {
  const width = size * thickness;
  const x = (size - width) / 2;

  return localRectPoints(x, 0, width, size);
}

/**
 * Углы
 */
const CORNER_TILE_RENDERERS: readonly TileRenderer[] = [
  ({ origin, size, palette }) => [fullCellRect(origin, size, palette.primary)],

  ({ origin, size, palette, rotation }) => [
    fullCellRect(origin, size, palette.primary),
    polygonInCell(
      origin,
      size,
      cornerCutTrianglePoints(size, 0.5),
      palette.surface,
      rotation
    ),
  ],

  ({ origin, size, palette, rotation }) => [
    fullCellRect(origin, size, palette.surface),
    polygonInCell(
      origin,
      size,
      topLeftTrianglePoints(size),
      palette.dark,
      rotation
    ),
  ],

  ({ origin, size, palette, rotation }) => [
    fullCellRect(origin, size, palette.secondary),
    polygonInCell(
      origin,
      size,
      diagonalBandPoints(size),
      palette.surface,
      rotation
    ),
  ],

  ({ origin, size, palette, rotation }) => [
    fullCellRect(origin, size, palette.surface),
    rectPolygonInCell(
      origin,
      size,
      0,
      0,
      size * 0.5,
      size * 0.5,
      palette.accent,
      rotation
    ),
  ],
];

/**
 * Края
 */
const EDGE_TILE_RENDERERS: readonly TileRenderer[] = [
  ({ origin, size, palette }) => [fullCellRect(origin, size, palette.secondary)],

  ({ origin, size, palette, rotation }) => [
    fullCellRect(origin, size, palette.primary),
    polygonInCell(
      origin,
      size,
      horizontalBandPoints(size, 0.34),
      palette.surface,
      rotation
    ),
  ],

  ({ origin, size, palette, rotation }) => [
    fullCellRect(origin, size, palette.secondary),
    polygonInCell(
      origin,
      size,
      topLeftTrianglePoints(size),
      palette.surface,
      rotation
    ),
  ],

  ({ origin, size, palette }) => [
    fullCellRect(origin, size, palette.primary),
    centeredCircleInCell(origin, size, palette.surface, 0.38),
  ],

  ({ origin, size, palette, rotation }) => [
    fullCellRect(origin, size, palette.primary),
    polygonInCell(
      origin,
      size,
      verticalBandPoints(size, 0.34),
      palette.surface,
      rotation
    ),
  ],
];

/**
 * Центр
 */
const CENTER_TILE_RENDERERS: readonly TileRenderer[] = [
  ({ origin, size, palette }) => [fullCellRect(origin, size, palette.primary)],

  ({ origin, size, palette }) => [
    fullCellRect(origin, size, palette.primary),
    centeredCircleInCell(origin, size, palette.surface, 0.34),
  ],

  ({ origin, size, palette }) => [
    fullCellRect(origin, size, palette.secondary),
    centeredCircleInCell(origin, size, palette.primary, 0.34),
  ],

  ({ origin, size, palette, rotation }) => [
    fullCellRect(origin, size, palette.primary),
    diamondInCell(origin, size, palette.surface, 2, rotation),
  ],

  ({ origin, size, palette, rotation }) => [
    fullCellRect(origin, size, palette.secondary),
    diamondInCell(origin, size, palette.primary, 3, rotation),
  ],

  ({ origin, size, palette }) => [
    fullCellRect(origin, size, palette.primary),
    rectPolygonInCell(
      origin,
      size,
      size * 0.26,
      size * 0.26,
      size * 0.48,
      size * 0.48,
      palette.surface
    ),
  ],
];

/**
 * Назначение функции: Выполняет операцию `pickTileIndex` для объекта «результат операции `pickTileIndex`». Возвращает результаты выражений: ``hashString(`${seed}::${scope}`) % total``.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function pickTileIndex(seed: string, scope: string, total: number) {
  return hashString(`${seed}::${scope}`) % total;
}

/**
 * Назначение функции: Отображает данные объекта «результат операции `renderGroup`»; операция `renderGroup`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function renderGroup(
  placements: readonly CellPlacement[],
  tileRenderer: TileRenderer,
  palette: Palette
): RenderShape[] {
  const baseShapes: RenderShape[] = [];
  const overlayShapes: RenderShape[] = [];

  placements.forEach((placement) => {
    const origin = cellOrigin(placement.row, placement.col);

    const tileShapes = tileRenderer({
      origin,
      size: CELL_SIZE,
      rotation: placement.rotation,
      palette,
    });

    if (tileShapes.length > 0) {
      baseShapes.push(tileShapes[0]);
    }

    if (tileShapes.length > 1) {
      overlayShapes.push(...tileShapes.slice(1));
    }
  });

  return [...baseShapes, ...overlayShapes];
}

/**
 * Назначение функции: Собирает данные объекта «результат операции `buildAvatarShapes`»; операция `buildAvatarShapes`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function buildAvatarShapes(
  seed: string,
  palette: Palette
): RenderShape[] {
  const cornerTile =
    CORNER_TILE_RENDERERS[
      pickTileIndex(seed, "corners", CORNER_TILE_RENDERERS.length)
    ];
  const horizontalTile =
    EDGE_TILE_RENDERERS[
      pickTileIndex(seed, "horizontal", EDGE_TILE_RENDERERS.length)
    ];
  const verticalTile =
    EDGE_TILE_RENDERERS[
      pickTileIndex(seed, "vertical", EDGE_TILE_RENDERERS.length)
    ];
  const centerTile =
    CENTER_TILE_RENDERERS[
      pickTileIndex(seed, "center", CENTER_TILE_RENDERERS.length)
    ];

  const rawShapes = [
    ...renderGroup(CORNER_CELLS, cornerTile, palette),
    ...renderGroup(HORIZONTAL_EDGE_CELLS, horizontalTile, palette),
    ...renderGroup(VERTICAL_EDGE_CELLS, verticalTile, palette),
    ...renderGroup(CENTER_CELLS, centerTile, palette),
  ];

  return mergeSeamSafePolygons(rawShapes);
}