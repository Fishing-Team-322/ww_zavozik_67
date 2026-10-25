"use client";

import { CheckpointWorkspace } from "@/src/features/checkpoint/CheckpointWorkspace";
import { useSession } from "@/src/features/auth";

export function MethodologyScreen() { const { company } = useSession(); return <CheckpointWorkspace key={company?.id ?? "none"} />; }
