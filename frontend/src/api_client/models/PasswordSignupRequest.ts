/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Request payload for creating an account with Email & Password.
 *
 * `terms_accepted` is the signup consent checkbox ("I agree to the Terms and
 * Privacy Policy and will not ship prohibited items"); the service rejects a
 * new account without it and stamps the accepted version server-side.
 */
export type PasswordSignupRequest = {
    email: string;
    password: string;
    full_name?: (string | null);
    terms_accepted?: boolean;
};

