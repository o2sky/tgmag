export type Account = {
  id: number;
  phoneMasked: string;
  userId: number | null;
  username: string | null;
  firstName: string | null;
  lastName: string | null;
  status: string;
  lastLoginAt: string | null;
};

export async function getAccounts(): Promise<Account[]> {
  // TODO: Replace the mock data when the server-side account API is available.
  return [
    {
      id: 1,
      phoneMasked: "+1 555 •••• 42",
      userId: 700000001,
      username: "alpha_ops",
      firstName: "Alpha",
      lastName: null,
      status: "active",
      lastLoginAt: "2026-08-05T12:30:00Z",
    },
    {
      id: 2,
      phoneMasked: "+44 7700 •••• 18",
      userId: 700000002,
      username: null,
      firstName: "Beta",
      lastName: "Team",
      status: "offline",
      lastLoginAt: "2026-08-01T09:10:00Z",
    },
    {
      id: 3,
      phoneMasked: "+55 11 9•••• 77",
      userId: null,
      username: null,
      firstName: null,
      lastName: null,
      status: "new",
      lastLoginAt: null,
    },
    {
      id: 4,
      phoneMasked: "+1 555 •••• 03",
      userId: 700000004,
      username: "delta_support",
      firstName: "Delta",
      lastName: "Ops",
      status: "error",
      lastLoginAt: "2026-07-28T18:45:00Z",
    },
  ];
}
