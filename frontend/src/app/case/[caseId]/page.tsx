import { Suspense } from "react";
import { CaseView } from "@/components/CaseView";

async function Case({ params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await params;
  return <CaseView target={{ kind: "live", caseId }} />;
}

export default function Page({ params }: { params: Promise<{ caseId: string }> }) {
  return <Suspense><Case params={params} /></Suspense>;
}
