import { notFound } from "next/navigation";
import { SectionView } from "@/src/components/workspace/SectionView";
import { sections, type Section } from "@/src/lib/sections";

export function generateStaticParams() {
  return sections.map((section) => ({ section }));
}

export default async function Page({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  if (!sections.includes(section as Section)) notFound();
  return <SectionView section={section as Section} />;
}
