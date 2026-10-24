import { CounterpartiesScreen } from "@/app/[section]/_ui/CounterpartiesScreen";
import { AccountGate } from "@/src/features/auth";
export default async function CounterpartyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AccountGate><CounterpartiesScreen id={id} /></AccountGate>;
}
