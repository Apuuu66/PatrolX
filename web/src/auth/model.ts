export type AuthRole = "admin" | "viewer";

export function canWrite(role?: string | null): boolean {
  return role === "admin";
}
