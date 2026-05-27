import { Card } from "@/components/ui/card";
import type { LucideIcon } from "lucide-react";

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon?: LucideIcon;
}) {
  return (
    <Card className="flex flex-col gap-1 py-4">
      <div className="flex items-center justify-between text-muted text-xs">
        <span>{label}</span>
        {Icon ? <Icon className="h-3.5 w-3.5 text-subtle" /> : null}
      </div>
      <p className="text-xl font-medium text-foreground tabular-nums">{value}</p>
      {hint ? <p className="text-xs text-subtle">{hint}</p> : null}
    </Card>
  );
}
