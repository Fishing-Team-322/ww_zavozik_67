"use client";

import { useId, useMemo } from "react";

import {
  buildAvatarShapes,
  CENTER,
  RADIUS,
  VIEWBOX_SIZE,
  type RenderShape,
} from "./CompanyIdenticonAvatar.parts";

type AvatarShape = "circle" | "rounded";

type CompanyIdenticonAvatarProps = {
  seed: string;
  size?: number;
  rounded?: number;
  shape?: AvatarShape;
  className?: string;
  title?: string;
};

type Palette = {
  background: string;
  surface: string;
  primary: string;
  secondary: string;
  accent: string;
  dark: string;
  border: string;
};

/**
 * Назначение функции: Приводит к единому виду данные объекта «результат операции `normalizeSeed`»; операция `normalizeSeed`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function normalizeSeed(seed: string) {
  const normalized = seed.trim();
  return normalized.length > 0 ? normalized : "default-avatar";
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
 * Назначение функции: Ограничивает данные объекта «результат операции `clamp`»; операция `clamp`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

/**
 * Назначение функции: Выполняет операцию `hsl` для объекта «результат операции `hsl`». Возвращает результаты выражений: ```hsla(${Math.round(h)} ${Math.round(s)}% ${Math.round(l)}% / ${a})```.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function hsl(h: number, s: number, l: number, a = 1) {
  return `hsla(${Math.round(h)} ${Math.round(s)}% ${Math.round(l)}% / ${a})`;
}

/**
 * Назначение функции: Выполняет операцию `mixHue` для объекта «результат операции `mixHue`». Возвращает результаты выражений: `(from + diff * weight + 360) % 360`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function mixHue(from: number, to: number, weight = 0.5) {
  const diff = ((((to - from) % 360) + 540) % 360) - 180;
  return (from + diff * weight + 360) % 360;
}

/**
 * Назначение функции: Создаёт данные объекта «результат операции `createPalette`»; операция `createPalette`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function createPalette(seedHash: number): Palette {
  const primaryHue = seedHash % 360;
  const secondaryHue = (primaryHue + 20 + ((seedHash >>> 4) % 40)) % 360;
  const accentHue = (primaryHue + 145 + ((seedHash >>> 10) % 35)) % 360;
  const neutralHue = mixHue(primaryHue, secondaryHue, 0.32);

  const backgroundLightness = 84 + ((seedHash >>> 16) % 4);
  const surfaceLightness = 92 + ((seedHash >>> 20) % 2);

  return {
    background: hsl(
      neutralHue,
      22 + ((seedHash >>> 7) % 8),
      backgroundLightness
    ),
    surface: hsl(neutralHue, 8 + ((seedHash >>> 12) % 5), surfaceLightness),
    primary: hsl(
      primaryHue,
      48 + ((seedHash >>> 2) % 12),
      48 + ((seedHash >>> 6) % 7)
    ),
    secondary: hsl(
      secondaryHue,
      32 + ((seedHash >>> 9) % 12),
      58 + ((seedHash >>> 14) % 8)
    ),
    accent: hsl(
      accentHue,
      42 + ((seedHash >>> 18) % 10),
      46 + ((seedHash >>> 22) % 8)
    ),
    dark: hsl(
      (neutralHue + 210) % 360,
      10 + ((seedHash >>> 24) % 8),
      22 + ((seedHash >>> 27) % 6)
    ),
    border: hsl(neutralHue, 10, clamp(backgroundLightness - 18, 62, 72), 0.9),
  };
}

/**
 * Назначение функции: Отображает данные объекта «результат операции `renderShape`»; операция `renderShape`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function renderShape(shapeItem: RenderShape, key: number) {
  if (shapeItem.kind === "rect") {
    return (
      <rect
        key={key}
        x={shapeItem.x}
        y={shapeItem.y}
        width={shapeItem.width}
        height={shapeItem.height}
        rx={shapeItem.rx}
        fill={shapeItem.fill}
      />
    );
  }

  if (shapeItem.kind === "circle") {
    return (
      <circle
        key={key}
        cx={shapeItem.cx}
        cy={shapeItem.cy}
        r={shapeItem.r}
        fill={shapeItem.fill}
      />
    );
  }

  if (shapeItem.kind === "path") {
    return <path key={key} d={shapeItem.d} fill={shapeItem.fill} />;
  }

  return (
    <polygon key={key} points={shapeItem.points} fill={shapeItem.fill} />
  );
}

/**
 * Назначение функции: Отображает компонент `CompanyIdenticonAvatar` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export default function CompanyIdenticonAvatar({
  seed,
  size = 176,
  rounded = 28,
  shape = "circle",
  className,
  title,
}: CompanyIdenticonAvatarProps) {
  const reactId = useId().replace(/:/g, "");
  const clipId = `${reactId}-clip`;

  const normalizedSeed = normalizeSeed(seed);
  const normalizedRounded = clamp(rounded, 0, VIEWBOX_SIZE / 2);

  const { palette, shapes } = useMemo(() => {
    const hashed = hashString(normalizedSeed);
    const generatedPalette = createPalette(hashed);
    const generatedShapes = buildAvatarShapes(normalizedSeed, generatedPalette);

    return {
      palette: generatedPalette,
      shapes: generatedShapes,
    };
  }, [normalizedSeed]);

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${VIEWBOX_SIZE} ${VIEWBOX_SIZE}`}
      className={className}
      role="img"
      aria-label={title ?? `Generated avatar for ${normalizedSeed}`}
      xmlns="http://www.w3.org/2000/svg"
      preserveAspectRatio="xMidYMid meet"
      style={{ display: "block" }}
    >
      {title ? <title>{title}</title> : null}

      <defs>
        <clipPath id={clipId}>
          {shape === "circle" ? (
            <circle cx={CENTER} cy={CENTER} r={RADIUS} />
          ) : (
            <rect
              x="0"
              y="0"
              width={VIEWBOX_SIZE}
              height={VIEWBOX_SIZE}
              rx={normalizedRounded}
              ry={normalizedRounded}
            />
          )}
        </clipPath>
      </defs>

      <g clipPath={`url(#${clipId})`}>
        <rect
          x="0"
          y="0"
          width={VIEWBOX_SIZE}
          height={VIEWBOX_SIZE}
          fill={palette.background}
        />

        {shapes.map(renderShape)}
      </g>

      {shape === "circle" ? (
        <circle
          cx={CENTER}
          cy={CENTER}
          r={RADIUS - 0.5}
          fill="none"
          stroke={palette.border}
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
      ) : (
        <rect
          x="0.5"
          y="0.5"
          width={VIEWBOX_SIZE - 1}
          height={VIEWBOX_SIZE - 1}
          rx={normalizedRounded}
          ry={normalizedRounded}
          fill="none"
          stroke={palette.border}
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
      )}
    </svg>
  );
}