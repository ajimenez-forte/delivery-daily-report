"use server";
import { revalidatePath } from "next/cache";
import { requireAdmin } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";

export async function aprobarImportacion() {
  await requireAdmin();
  const supabase = await createClient();
  const { data: resumen, error: e1 } = await supabase.rpc("resumen_importacion");
  if (e1) throw new Error(e1.message);
  const { error } = await supabase.rpc("aprobar_importacion", { p_resumen: resumen });
  if (error) throw new Error(error.message);
  revalidatePath("/admin");
}
