// API client — typed fetch wrapper for Ragas Platform backend

export interface Project {
  id: number;
  name: string;
  description: string;
  created_at: string;
}

interface CreateProjectPayload {
  name: string;
  description: string;
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, `${res.status}: ${body}`);
  }

  return res.json() as Promise<T>;
}

export async function fetchProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export async function createProject(
  payload: CreateProjectPayload,
): Promise<Project> {
  return request<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
