/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { UserRead } from './UserRead';
/**
 * Supabase-compatible session + synced Naviera user profile.
 */
export type PasswordAuthResponse = {
    access_token: string;
    refresh_token: string;
    token_type?: string;
    expires_in: number;
    expires_at: number;
    supabase_user_id: string;
    user: UserRead;
};

