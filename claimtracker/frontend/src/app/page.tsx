"use client";

/**
 * Landing route. There is no marketing page, so send people where they can
 * actually act: the claims list when signed in, otherwise sign-in.
 */
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Spinner } from "@/components/Spinner";
import { useAuth } from "@/lib/auth/AuthProvider";

export default function HomePage() {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") return;
    router.replace(status === "authenticated" ? "/claims" : "/login");
  }, [status, router]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <Spinner label="Loading ClaimTracker" className="h-8 w-8" />
    </div>
  );
}
