import { Suspense } from "react";
import { CaseView } from "@/components/CaseView";

async function Replay({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  return <CaseView target={{ kind: "replay", name }} />;
}

export default function Page({ params }: { params: Promise<{ name: string }> }) {
  return <Suspense><Replay params={params} /></Suspense>;
}
