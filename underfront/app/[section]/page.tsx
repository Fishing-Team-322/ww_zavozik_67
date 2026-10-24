import { notFound } from "next/navigation";
import { SectionView } from "@/app/[section]/_ui/SectionView";
import { sections, type Section } from "@/src/entities/navigation";

export function generateStaticParams() {
  return sections.map((section) => ({ section }));
}

export default async function Page({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  if (!sections.includes(section as Section)) notFound();
  return <SectionView section={section as Section} />;
}
