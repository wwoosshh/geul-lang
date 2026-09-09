import { permitted } from "./policy";

export function DeleteButton(
  user: { role: string; suspended: boolean },
  owner: boolean,
  locked: boolean,
  visible: boolean,
) {
  if (!visible) return null;
  const disabled = !permitted(user, owner) || locked;
  return <button disabled={disabled}>삭제</button>;
}
