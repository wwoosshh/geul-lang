import { permitted as canDelete } from "./policy";

export function disabled(
  user: { role: string; suspended: boolean },
  owner: boolean,
  locked: boolean,
) {
  const allowed = canDelete(user, owner);
  return !allowed || locked;
}
