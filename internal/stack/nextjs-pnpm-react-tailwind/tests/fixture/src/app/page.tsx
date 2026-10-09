// Migrated from `function App()` in design/mock.html. No state/effects, so it
// stays a Server Component; interactive pieces are imported Client Components.
import Counter from "@/components/Counter";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-4xl font-bold text-slate-900">
        STACK-FIXTURE-MARKER nextjs-pnpm-react-tailwind
      </h1>
      <p className="text-slate-600">Hand-migrated from design/mock.html.</p>
      <Counter />
    </main>
  );
}
