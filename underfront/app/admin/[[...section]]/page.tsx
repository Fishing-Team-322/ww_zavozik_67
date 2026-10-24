import { notFound } from "next/navigation";
import { AdminScreen } from "../_ui/AdminScreen";
export default async function AdminPage({ params }: { params: Promise<{ section?: string[] }> }) {
  const section = (await params).section?.join("/") || "overview";
  if (!["overview", "users", "companies", "integrations", "models", "classifier", "antifraud/signals", "audit"].includes(section)) notFound();
  return <AdminScreen key={section} section={section} />;
}
