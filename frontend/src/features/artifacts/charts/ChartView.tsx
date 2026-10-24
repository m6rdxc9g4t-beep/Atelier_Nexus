"use client";

/**
 * Dessin SVG des graphiques `atelier-chart/1` (histogramme, boîtes à moustaches, nuage de
 * points, barres, courbes, carte de chaleur). Couleurs = jetons du design system (classes
 * Tailwind) ; info-bulles natives (`<title>`) sur chaque marque.
 */

import { type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { type Axis, type ChartSpec, formatTick, linear, niceTicks } from "./spec";

const W = 560;
const H = 320;
const M = { top: 14, right: 16, left: 60 };
const PW = W - M.left - M.right;

/** Hauteur de la zone de tracé : plus de marge basse quand les libellés sont inclinés. */
interface Layout {
  bottom: number;
  ph: number;
}
const layout = (rotated = false): Layout => {
  const bottom = rotated ? 78 : 48;
  return { bottom, ph: H - M.top - bottom };
};
const rotates = (labels: string[]) =>
  labels.length > 8 || (labels.length > 4 && labels.some((label) => label.length > 14));

/** Couleurs des séries : la signature d'abord, puis la palette multi-séries. */
const FILL = ["fill-primary", "fill-chart-2", "fill-chart-3", "fill-chart-4", "fill-chart-5", "fill-chart-1"];
const STROKE = ["stroke-primary", "stroke-chart-2", "stroke-chart-3", "stroke-chart-4", "stroke-chart-5", "stroke-chart-1"];
const SWATCH = ["bg-primary", "bg-chart-2", "bg-chart-3", "bg-chart-4", "bg-chart-5", "bg-chart-1"];

const fr = (v: number) => v.toLocaleString("fr-FR", { maximumFractionDigits: 3 });
const short = (s: string, n = 16) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

export function ChartView({ spec }: { spec: ChartSpec }) {
  let body: ReactNode;
  let legend: string[] = [];
  switch (spec.type) {
    case "histogram":
      body = <Histogram spec={spec} />;
      legend = spec.markers.map((m) => `${m.label} : ${fr(m.value)}`);
      break;
    case "box":
      body = <Boxes spec={spec} />;
      break;
    case "scatter":
      body = <Scatter spec={spec} />;
      legend = spec.groups ? [...new Set(spec.groups)].slice(0, SWATCH.length) : [];
      break;
    case "bar":
    case "line":
      body = <Categories spec={spec} />;
      legend = spec.series.length > 1 ? spec.series.map((s) => s.name) : [];
      break;
    case "heatmap":
      return <Heatmap spec={spec} />;
  }
  return (
    <figure className="space-y-2">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={spec.title} className="h-auto w-full overflow-visible">
        {body}
      </svg>
      {legend.length > 0 && (
        <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {legend.map((label, i) => (
            <span key={label} className="inline-flex items-center gap-1.5">
              <span
                aria-hidden
                className={cn(
                  "inline-block size-2.5 rounded-sm",
                  spec.type === "histogram" ? (i === 0 ? "bg-foreground" : "bg-chart-2") : SWATCH[i % SWATCH.length],
                )}
              />
              {label}
            </span>
          ))}
        </figcaption>
      )}
      {spec.type === "scatter" && spec.sampled && (
        <p className="text-xs text-muted-foreground">
          {spec.points.length.toLocaleString("fr-FR")} points affichés sur {spec.total.toLocaleString("fr-FR")}.
        </p>
      )}
    </figure>
  );
}

// ─── Axes ──────────────────────────────────────────────────────────

function YAxis({
  ticks,
  scale,
  label,
  l,
}: {
  ticks: number[];
  scale: (v: number) => number;
  label: string;
  l: Layout;
}) {
  return (
    <g>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={M.left} x2={W - M.right} y1={scale(t)} y2={scale(t)} className="stroke-border" strokeWidth={1} />
          <text x={M.left - 6} y={scale(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[10px]">
            {formatTick(t)}
          </text>
        </g>
      ))}
      {label && (
        <text
          transform={`translate(14 ${M.top + l.ph / 2}) rotate(-90)`}
          textAnchor="middle"
          className="fill-muted-foreground text-[11px]"
        >
          {short(label, 40)}
        </text>
      )}
    </g>
  );
}

function XAxisNumeric({
  ticks,
  scale,
  axis,
  l,
}: {
  ticks: number[];
  scale: (v: number) => number;
  axis: Axis;
  l: Layout;
}) {
  return (
    <g>
      <line x1={M.left} x2={W - M.right} y1={M.top + l.ph} y2={M.top + l.ph} className="stroke-border-strong" />
      {ticks.map((t) => (
        <text key={t} x={scale(t)} y={M.top + l.ph + 16} textAnchor="middle" className="fill-muted-foreground text-[10px]">
          {formatTick(t, axis.kind)}
        </text>
      ))}
      <XLabel label={axis.label} />
    </g>
  );
}

function XLabel({ label }: { label: string }) {
  if (!label) return null;
  return (
    <text x={M.left + PW / 2} y={H - 6} textAnchor="middle" className="fill-muted-foreground text-[11px]">
      {short(label, 60)}
    </text>
  );
}

function XAxisBands({ labels, center, l }: { labels: string[]; center: (i: number) => number; l: Layout }) {
  const rotate = rotates(labels);
  const step = Math.max(1, Math.ceil(labels.length / 24));
  return (
    <g>
      <line x1={M.left} x2={W - M.right} y1={M.top + l.ph} y2={M.top + l.ph} className="stroke-border-strong" />
      {labels.map((label, i) =>
        i % step ? null : (
          <text
            key={`${label}-${i}`}
            transform={`translate(${center(i)} ${M.top + l.ph + 14})${rotate ? " rotate(-35)" : ""}`}
            textAnchor={rotate ? "end" : "middle"}
            className="fill-muted-foreground text-[10px]"
          >
            <title>{label}</title>
            {short(label, rotate ? 12 : 16)}
          </text>
        ),
      )}
    </g>
  );
}

// ─── Histogramme ───────────────────────────────────────────────────

function Histogram({ spec }: { spec: Extract<ChartSpec, { type: "histogram" }> }) {
  const lo = spec.bins[0].start;
  const hi = spec.bins[spec.bins.length - 1].end;
  const yTicks = niceTicks(0, Math.max(...spec.bins.map((b) => b.count)));
  const x = linear(lo, hi, M.left, W - M.right);
  const l = layout();
  const y = linear(0, yTicks[yTicks.length - 1], M.top + l.ph, M.top);
  const xTicks = niceTicks(lo, hi, 6).filter((t) => t >= lo && t <= hi);
  return (
    <g>
      <YAxis ticks={yTicks} scale={y} label={spec.y.label} l={l} />
      {spec.bins.map((b, i) => (
        <rect
          key={i}
          x={x(b.start) + 0.5}
          y={y(b.count)}
          width={Math.max(1, x(b.end) - x(b.start) - 1)}
          height={M.top + l.ph - y(b.count)}
          className="fill-primary"
          fillOpacity={0.75}
        >
          <title>{`${formatTick(b.start, spec.x.kind)} – ${formatTick(b.end, spec.x.kind)} : ${b.count}`}</title>
        </rect>
      ))}
      {spec.markers.map((m, i) =>
        m.value >= lo && m.value <= hi ? (
          <line
            key={m.label}
            x1={x(m.value)}
            x2={x(m.value)}
            y1={M.top}
            y2={M.top + l.ph}
            className={i === 0 ? "stroke-foreground" : "stroke-chart-2"}
            strokeWidth={1.5}
            strokeDasharray={i === 0 ? undefined : "4 3"}
          >
            <title>{`${m.label} : ${fr(m.value)}`}</title>
          </line>
        ) : null,
      )}
      <XAxisNumeric ticks={xTicks} scale={x} axis={spec.x} l={l} />
    </g>
  );
}

// ─── Boîtes à moustaches ───────────────────────────────────────────

function Boxes({ spec }: { spec: Extract<ChartSpec, { type: "box" }> }) {
  const all = spec.groups.flatMap((g) => [g.min, g.max, ...g.outliers]);
  const yTicks = niceTicks(Math.min(...all), Math.max(...all));
  const labels = spec.groups.map((g) => g.label);
  const l = layout(rotates(labels));
  const y = linear(yTicks[0], yTicks[yTicks.length - 1], M.top + l.ph, M.top);
  const band = PW / spec.groups.length;
  const center = (i: number) => M.left + band * (i + 0.5);
  const half = Math.min(28, band * 0.3);
  return (
    <g>
      <YAxis ticks={yTicks} scale={y} label={spec.y.label} l={l} />
      {spec.groups.map((g, i) => {
        const cx = center(i);
        return (
          <g key={`${g.label}-${i}`}>
            <title>
              {`${g.label} (n = ${g.n})\nmin ${fr(g.min)} · Q1 ${fr(g.q1)} · médiane ${fr(g.median)} · Q3 ${fr(g.q3)} · max ${fr(g.max)}` +
                (g.mean !== null ? `\nmoyenne ${fr(g.mean)}` : "")}
            </title>
            <line x1={cx} x2={cx} y1={y(g.min)} y2={y(g.q1)} className="stroke-muted-foreground" />
            <line x1={cx} x2={cx} y1={y(g.q3)} y2={y(g.max)} className="stroke-muted-foreground" />
            <line x1={cx - half / 2} x2={cx + half / 2} y1={y(g.min)} y2={y(g.min)} className="stroke-muted-foreground" />
            <line x1={cx - half / 2} x2={cx + half / 2} y1={y(g.max)} y2={y(g.max)} className="stroke-muted-foreground" />
            <rect
              x={cx - half}
              y={y(g.q3)}
              width={half * 2}
              height={Math.max(1, y(g.q1) - y(g.q3))}
              className="fill-primary stroke-primary"
              fillOpacity={0.25}
              rx={2}
            />
            <line x1={cx - half} x2={cx + half} y1={y(g.median)} y2={y(g.median)} className="stroke-primary" strokeWidth={2} />
            {g.mean !== null && (
              <circle cx={cx} cy={y(g.mean)} r={2.5} className="fill-card stroke-foreground" strokeWidth={1.2} />
            )}
            {g.outliers.map((o, k) => (
              <circle key={k} cx={cx} cy={y(o)} r={2.2} className="fill-chart-2" fillOpacity={0.7}>
                <title>{fr(o)}</title>
              </circle>
            ))}
          </g>
        );
      })}
      <XAxisBands labels={labels} center={center} l={l} />
      <XLabel label={spec.x.label} />
    </g>
  );
}

// ─── Nuage de points ───────────────────────────────────────────────

function Scatter({ spec }: { spec: Extract<ChartSpec, { type: "scatter" }> }) {
  const xs = spec.points.map((p) => p[0]);
  const ys = spec.points.map((p) => p[1]);
  const xTicks = niceTicks(Math.min(...xs), Math.max(...xs), 6);
  const yTicks = niceTicks(Math.min(...ys), Math.max(...ys));
  const l = layout();
  const x = linear(xTicks[0], xTicks[xTicks.length - 1], M.left, W - M.right);
  const y = linear(yTicks[0], yTicks[yTicks.length - 1], M.top + l.ph, M.top);
  const groupIndex = new Map<string, number>();
  for (const g of spec.groups ?? []) if (!groupIndex.has(g)) groupIndex.set(g, groupIndex.size);
  const t = spec.trend;
  const x0 = xTicks[0];
  const x1 = xTicks[xTicks.length - 1];
  return (
    <g>
      <YAxis ticks={yTicks} scale={y} label={spec.y.label} l={l} />
      <g>
        {spec.points.map(([px, py], i) => {
          const gi = spec.groups ? (groupIndex.get(spec.groups[i]) ?? 0) % FILL.length : 0;
          return (
            <circle key={i} cx={x(px)} cy={y(py)} r={2.6} className={FILL[gi]} fillOpacity={0.55}>
              <title>{`${spec.groups ? `${spec.groups[i]} · ` : ""}${formatTick(px, spec.x.kind)} ; ${fr(py)}`}</title>
            </circle>
          );
        })}
      </g>
      {t && (
        <line
          x1={x(x0)}
          y1={y(t.slope * x0 + t.intercept)}
          x2={x(x1)}
          y2={y(t.slope * x1 + t.intercept)}
          className="stroke-foreground"
          strokeWidth={1.5}
          strokeDasharray="5 4"
        >
          <title>{`Tendance : y = ${fr(t.slope)} × x + ${fr(t.intercept)}${t.r2 !== null ? ` (R² = ${fr(t.r2)})` : ""}`}</title>
        </line>
      )}
      <XAxisNumeric ticks={xTicks} scale={x} axis={spec.x} l={l} />
    </g>
  );
}

// ─── Barres et courbes ─────────────────────────────────────────────

function Categories({ spec }: { spec: Extract<ChartSpec, { type: "bar" | "line" }> }) {
  const values = spec.series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  const yTicks = niceTicks(Math.min(0, ...values), Math.max(0, ...values));
  const l = layout(rotates(spec.categories));
  const y = linear(yTicks[0], yTicks[yTicks.length - 1], M.top + l.ph, M.top);
  const n = spec.categories.length;
  const band = PW / n;
  const center = (i: number) => M.left + band * (i + 0.5);
  const inner = (band * 0.8) / spec.series.length;
  return (
    <g>
      <YAxis ticks={yTicks} scale={y} label={spec.y.label} l={l} />
      {spec.type === "bar"
        ? spec.series.map((s, si) =>
            s.values.map((v, i) =>
              v === null ? null : (
                <rect
                  key={`${si}-${i}`}
                  x={M.left + band * i + band * 0.1 + inner * si}
                  y={Math.min(y(v), y(0))}
                  width={Math.max(1, inner - 1)}
                  height={Math.max(1, Math.abs(y(0) - y(v)))}
                  className={FILL[si % FILL.length]}
                  rx={1.5}
                >
                  <title>{`${spec.categories[i]}${spec.series.length > 1 ? ` · ${s.name}` : ""} : ${fr(v)}`}</title>
                </rect>
              ),
            ),
          )
        : spec.series.map((s, si) => {
            const pts = s.values.map((v, i) => (v === null ? null : ([center(i), y(v)] as const)));
            const d = pts
              .map((p, i) => (p ? `${i === 0 || !pts[i - 1] ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}` : ""))
              .join("");
            return (
              <g key={si}>
                <path d={d} fill="none" className={STROKE[si % STROKE.length]} strokeWidth={2} />
                {n <= 60 &&
                  s.values.map((v, i) =>
                    v === null ? null : (
                      <circle key={i} cx={center(i)} cy={y(v)} r={2.5} className={FILL[si % FILL.length]}>
                        <title>{`${spec.categories[i]} · ${s.name} : ${fr(v)}`}</title>
                      </circle>
                    ),
                  )}
              </g>
            );
          })}
      <XAxisBands labels={spec.categories} center={center} l={l} />
      <XLabel label={spec.x.label} />
    </g>
  );
}

// ─── Carte de chaleur (corrélations) ───────────────────────────────

function Heatmap({ spec }: { spec: Extract<ChartSpec, { type: "heatmap" }> }) {
  const k = spec.labels.length;
  const left = 120;
  const top = 96;
  const cell = Math.max(14, Math.min(48, (W - left - 8) / k));
  const size = cell * k;
  const width = left + size + 8;
  const height = top + size + 8;
  const maxAbs = Math.max(Math.abs(spec.domain[0]), Math.abs(spec.domain[1])) || 1;
  return (
    <figure className="space-y-2">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={spec.title}
        className={cn("h-auto w-full", k <= 4 ? "max-w-sm" : k <= 8 ? "max-w-md" : undefined)}
      >
        {spec.labels.map((l, i) => (
          <g key={`${l}-${i}`}>
            <text x={left - 6} y={top + cell * (i + 0.5)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[10px]">
              <title>{l}</title>
              {short(l, 18)}
            </text>
            <text
              transform={`translate(${left + cell * (i + 0.5)} ${top - 6}) rotate(-45)`}
              className="fill-muted-foreground text-[10px]"
            >
              <title>{l}</title>
              {short(l, 18)}
            </text>
          </g>
        ))}
        {spec.values.map((row, i) =>
          row.map((v, j) => (
            <g key={`${i}-${j}`}>
              <rect
                x={left + cell * j + 0.5}
                y={top + cell * i + 0.5}
                width={cell - 1}
                height={cell - 1}
                rx={2}
                className={v === null ? "fill-muted" : v >= 0 ? "fill-primary" : "fill-chart-2"}
                fillOpacity={v === null ? 1 : 0.12 + 0.88 * Math.min(1, Math.abs(v) / maxAbs)}
              >
                <title>{`${spec.labels[i]} × ${spec.labels[j]} : ${v === null ? "non calculé" : fr(v)}`}</title>
              </rect>
              {v !== null && cell >= 30 && (
                <text
                  x={left + cell * (j + 0.5)}
                  y={top + cell * (i + 0.5)}
                  dy="0.32em"
                  textAnchor="middle"
                  className={cn("text-[10px] tabular-nums", Math.abs(v) / maxAbs > 0.6 ? "fill-primary-foreground" : "fill-foreground")}
                >
                  {v.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}
                </text>
              )}
            </g>
          )),
        )}
      </svg>
      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>{spec.legend}</span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block size-2.5 rounded-sm bg-chart-2" /> négative
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block size-2.5 rounded-sm bg-primary" /> positive
        </span>
        <span>intensité = force</span>
      </figcaption>
    </figure>
  );
}
