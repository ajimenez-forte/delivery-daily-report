"use server";
import { revalidatePath } from "next/cache";
import { requireAdmin } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";

const MARKS = new Set(["hecho", "pendiente", "no_tocado"]);

export async function marcarLinea(itemId: number, formData: FormData) {
  await requireAdmin();
  const mark = String(formData.get("mark") ?? "");
  const supabase = await createClient();
  const { error } = mark === "descartar"
    ? await supabase.rpc("descartar_linea", { p_item: itemId })
    : MARKS.has(mark)
      ? await supabase.rpc("resolver_linea", { p_item: itemId, p_mark: mark, p_text: String(formData.get("text") ?? "") })
      : { error: { message: "Elige una marca." } };
  if (error) throw new Error(error.message);
  revalidatePath("/admin/revision");
}
