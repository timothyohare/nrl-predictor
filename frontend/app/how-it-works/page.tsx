export const dynamic = "force-static";

export default function HowItWorksPage() {
  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <h1 className="text-2xl font-bold text-nrl-blue">How It Works</h1>

      <Section title="1. Team sheets scraped automatically">
        <p>
          Every Thursday and Friday night, official NRL team sheets are published on nrl.com. Within
          minutes of publication, our scraper fetches the full 17 for every match and stores it.
          Any late changes (jersey swaps in positions 7–10) trigger an automatic re-prediction.
        </p>
      </Section>

      <Section title="2. Context gathered from multiple sources">
        <p>Before generating a prediction, the AI collects:</p>
        <ul className="mt-2 space-y-1 list-disc list-inside text-sm">
          <li>Both teams&apos; confirmed 17s</li>
          <li>Recent form (last 5 results) for each team</li>
          <li>Head-to-head record at the venue</li>
          <li>Current ladder positions and points differential</li>
          <li>Weather forecast for match day</li>
          <li>Injury news from NRL media (last 48 hours)</li>
        </ul>
      </Section>

      <Section title="3. AI reasoning with Claude">
        <p>
          We use Anthropic&apos;s Claude to analyse all available context and write out its reasoning
          before settling on a prediction. The model defaults to{" "}
          <span className="font-mono text-sm bg-gray-100 px-1 rounded">claude-haiku-4-5</span> for
          regular rounds and upgrades to{" "}
          <span className="font-mono text-sm bg-gray-100 px-1 rounded">claude-sonnet-4-6</span> for
          finals or when key playmakers (halfback, hooker, five-eighth, lock) are late changes.
        </p>
        <p className="mt-2">
          The model is given a strict JSON output schema and validates its own prediction before
          returning it — ensuring team names, confidence levels, and key factors are always
          well-formed.
        </p>
      </Section>

      <Section title="4. Confidence levels explained">
        <dl className="mt-2 space-y-2 text-sm">
          <div>
            <dt className="inline font-semibold text-green-700">HIGH</dt>
            <dd className="inline text-gray-600">
              {" "}— clear favourite on form, venue, and team composition. Brier probability: 0.85.
            </dd>
          </div>
          <div>
            <dt className="inline font-semibold text-yellow-700">MEDIUM</dt>
            <dd className="inline text-gray-600">
              {" "}— meaningful edge identified but notable uncertainty. Brier probability: 0.65.
            </dd>
          </div>
          <div>
            <dt className="inline font-semibold text-red-700">LOW</dt>
            <dd className="inline text-gray-600">
              {" "}— genuinely contested match; result could go either way. Brier probability: 0.55.
            </dd>
          </div>
        </dl>
      </Section>

      <Section title="5. Accuracy tracking">
        <p>
          Every prediction is stored. Once a match result is confirmed, the prediction is scored
          automatically — winner correct or not, margin error, and a Brier score that penalises
          overconfident wrong picks. All results are published on the{" "}
          <a href="/accuracy" className="text-blue-600 hover:underline">Accuracy</a> page,
          including rounds where we performed poorly.
        </p>
      </Section>

      <p className="text-xs text-gray-400 border-t pt-4">
        Predictions are generated for entertainment purposes only. They are not betting advice.
        Always conduct your own research.
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-xl border p-6 space-y-2">
      <h2 className="font-semibold text-gray-800">{title}</h2>
      <div className="text-sm text-gray-600 leading-relaxed">{children}</div>
    </section>
  );
}
