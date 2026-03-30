import { http } from "./client";
import { LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, Space } from "../types";

export async function login(data: LoginRequest): Promise<LoginResponse> {
  return await http<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    json: data,
  });
}

export async function register(data: RegisterRequest): Promise<RegisterResponse> {
  return await http<RegisterResponse>("/api/v1/auth/register", {
    method: "POST",
    json: data,
  });
}

export async function getSpaces(limit?: number, offset?: number): Promise<Space[]> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  return await http<Space[]>(`/api/v1/spaces?${params.toString()}`);
}

export async function createSpace(name: string): Promise<Space> {
  return await http<Space>("/api/v1/spaces", {
    method: "POST",
    json: { name },
  });
}

export async function deleteSpace(spaceId: string): Promise<void> {
  await http(`/api/v1/spaces/${spaceId}`, {
    method: "DELETE",
  });
}

export async function switchSpace(spaceId: string): Promise<Space> {
  return await http<Space>(`/api/v1/spaces/${spaceId}/switch`, {
    method: "POST",
  });
}
