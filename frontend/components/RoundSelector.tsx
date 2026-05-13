"use client";

import { useRouter } from "next/navigation";

const ROUNDS = Array.from({ length: 27 }, (_, i) => i + 1);
const FINALS = [
  { label: "Finals W1", value: 28 },
  { label: "Semi Finals", value: 29 },
  { label: "Prelim Finals", value: 30 },
  { label: "Grand Final", value: 31 },
];

export default function RoundSelector({ current }: { current: number }) {
  const router = useRouter();

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <label className="text-sm text-gray-500" htmlFor="round-select">Round:</label>
      <select
        id="round-select"
        value={current}
        onChange={(e) => router.push(`/predictions/${e.target.value}`)}
        className="border rounded px-2 py-1 text-sm bg-white"
      >
        {ROUNDS.map((r) => (
          <option key={r} value={r}>Round {r}</option>
        ))}
        {FINALS.map((f) => (
          <option key={f.value} value={f.value}>{f.label}</option>
        ))}
      </select>
    </div>
  );
}
