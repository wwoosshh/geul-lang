export function permitted(user: { role: string; suspended: boolean }, owner: boolean) {
  if (user.suspended) return false;
  return user.role === "admin" || owner;
}
