"use server";
import { revalidatePath } from "next/cache";
import { requireAdmin } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";

// El autor de la nota lo pone la base (guardar_nota usa el correo del token). La app no lo envía.
export async function guardarNota(personId: number, formData: FormData) {
  await requireAdmin();
  const supabase = await createClient();
  const { error } = await supabase.rpc("guardar_nota", { p_person: personId, p_body: String(formData.get("body") ?? "") });
  if (error) throw new Error(error.message);
  revalidatePath(`/admin/persona/${personId}`);
}
