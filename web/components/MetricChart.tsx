"use client";

import { metricKeysFromPoints } from "@/lib/api";
import type { MetricPoint } from "@/lib/types";
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const GRID = "#d4dbe4";
const AXIS = "#8b95a5";
const LINE = "#1a6b5c";

export function MetricChart({ points }: { points: MetricPoint[] }) {
  const keys = useMemo(() => metricKeysFromPoints(points), [points]);
  const [metric, setMetric] = useState(keys[0] ?? "loss");

  const data = useMemo(() => {
    return points.map((p) => ({
      step: p.step,
      value:
        p.metrics && metric in p.metrics ? p.metrics[metric] : null,
    }));
  }, [points, metric]);

  if (!points.length) {
    return (
      <p className="text-sm text-muted py-8 text-center">No metrics logged yet.</p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <label className="flex items-center gap-2 text-sm text-muted">
          Metric
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className="rounded-lg border border-border bg-surface-elevated px-2 py-1 text-foreground text-sm"
          >
            {keys.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
            <XAxis
              dataKey="step"
              stroke={AXIS}
              tick={{ fill: AXIS, fontSize: 12 }}
            />
            <YAxis stroke={AXIS} tick={{ fill: AXIS, fontSize: 12 }} />
            <Tooltip
              contentStyle={{
                background: "#ffffff",
                border: "1px solid #d4dbe4",
                borderRadius: 8,
              }}
            />
            <Line
              type="monotone"
              dataKey="value"
              name={metric}
              stroke={LINE}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
