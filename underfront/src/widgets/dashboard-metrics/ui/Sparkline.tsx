"use client";

import { useId } from "react";

/**
 * The shape of a number over the period, behind the number itself.
 *
 * Drawn as plain SVG rather than through the chart library: a tile carries one
 * unlabelled series at 40px tall, where an axis, a tooltip and a responsive
 * container are all cost without a reader. Anything a reader can interrogate
 * belongs in a real chart panel instead.
 */
/**
 * Назначение функции: The shape of a number over the period, behind the number itself. Drawn as plain SVG rather than through the chart library: a tile carries one unlabelled series at 40px tall, where an axis, a tooltip and a responsive container are all cost without a reader. Anything a reader can interrogate belongs in a real chart panel instead.
 * Зачем используется: Поддерживает отдельное действие или сценарий пользователя.
 */
export function Sparkline({
  values,
  color,
  height = 40,
  filled = true,
}: {
  values: number[];
  color: string;
  height?: number;
  filled?: boolean;
}) {
  const uid = useId().replace(/:/g, "");
  if (values.length < 2) return <div style={{ height }} />;

  const width = 100;
  const min = Math.min(...values, 0);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);

  const points = values.map((value, index) => {
    const x = index * step;
    const y = height - ((value - min) / span) * (height - 4) - 2;
    return [x, y] as const;
  });

  const line = points
    .map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(" ");
  const area = `${line} L${width} ${height} L0 ${height} Z`;

  return (
    <svg
      aria-hidden
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      width="100%"
      height={height}
      style={{ display: "block", overflow: "visible" }}
    >
      {filled ? (
        <>
          <defs>
            <linearGradient id={`spark-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#spark-${uid})`} />
        </>
      ) : null}
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/**
 * The same series as columns, for a table row where a line would read as a
 * trend and the reader wants per-period magnitude.
 */
/**
 * Назначение функции: The same series as columns, for a table row where a line would read as a trend and the reader wants per-period magnitude.
 * Зачем используется: Поддерживает отдельное действие или сценарий пользователя.
 */
export function BarSparkline({
  values,
  color,
  height = 26,
}: {
  values: number[];
  color: string;
  height?: number;
}) {
  if (values.length === 0) return <div style={{ height }} />;
  const max = Math.max(...values, 0) || 1;

  return (
    <div
      aria-hidden
      className="flex items-end gap-[2px]"
      style={{ height }}
    >
      {values.map((value, index) => (
        <span
          key={index}
          className="w-[3px] shrink-0 rounded-[1px]"
          style={{
            height: `${Math.max(2, (Math.max(value, 0) / max) * height)}px`,
            background: color,
            opacity: 0.35 + 0.65 * (Math.max(value, 0) / max),
          }}
        />
      ))}
    </div>
  );
}
