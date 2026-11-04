// user.profile is optional: guests have no profile.
export function displayName(user) {
  return user.profile.nickname || user.email;
}
