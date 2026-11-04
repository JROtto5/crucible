// user.profile is optional: guests have no profile.
export function displayName(user) {
  if (!user.profile || !user.profile.nickname) return user.email;
  return user.profile.nickname;
}
