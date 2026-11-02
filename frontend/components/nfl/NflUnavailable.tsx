/** Shown instead of NFL content when NFL_API_BASE_URL is unset or the API fails. */
export default function NflUnavailable() {
  return (
    <div role="status" className="bg-nrl-paper rounded-xl border-2 border-gray-200 p-8 text-center text-gray-700">
      <p className="text-lg font-semibold">NFL predictions unavailable</p>
      <p className="text-sm mt-1">The NFL data service can&apos;t be reached right now. Please check back later.</p>
    </div>
  );
}
