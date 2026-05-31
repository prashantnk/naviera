import httpx
from app.core.config import settings
from supabase_auth import AuthResponse

# --- Configuration ---
# These are the credentials for the user we created in the Supabase UI
TEST_USER_EMAIL = "naviera_test_user@naviera.com"
TEST_USER_PASSWORD = "NavieraTestUser"
TENANT_SLUG = "naviera"
API_BASE_URL = "http://localhost:8000"
# ---
from supabase import Client, create_client


def test_onboarding_flow():
    """
    Simulates a full frontend login and onboarding flow.
    1. Authenticates a user with Supabase to get a real JWT.
    2. Calls our backend's /onboard endpoint with the JWT.
    """
    print("--- Starting End-to-End Auth Test ---")

    # 1. Authenticate with Supabase to get a real session
    print(f"Attempting to sign in user '{TEST_USER_EMAIL}' with Supabase...")
    try:
        supabase: Client = create_client(
            settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY
        )
        response: AuthResponse = supabase.auth.sign_in_with_password(
            {"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}
        )
        jwt = response.session.access_token  # type: ignore
        print("✅ Supabase sign-in successful.")
        print(f"JWT: {jwt}")
        print(f"\nsettings: {settings}")
    except Exception as e:
        print(f"❌ Supabase sign-in failed: {e}")
        return

    # 2. Call our backend's /onboard endpoint
    print(f"Calling backend /onboard endpoint for tenant '{TENANT_SLUG}'...")
    headers = {"Authorization": f"Bearer {jwt}", "X-Tenant-Slug": TENANT_SLUG}

    try:
        # Increase the timeout to 30 seconds to make the test more robust
        timeout = httpx.Timeout(30.0)
        with httpx.Client(timeout=timeout) as client:
            api_response = client.post(
                f"{API_BASE_URL}{settings.API_V1_STR}/users/onboard", headers=headers
            )

        print(f"✅ Backend response received. Status Code: {api_response.status_code}")

        # Raise an exception if the status code indicates an error (e.g., 4xx or 5xx)
        api_response.raise_for_status()

        user_data = api_response.json()
        print("--- Onboarding Successful ---")
        print(f"User ID: {user_data['id']}")
        print(f"User Email: {user_data['email']}")
        print(f"Tenant ID: {user_data['tenant_id']}")
        print("---------------------------")

    except httpx.HTTPStatusError as e:
        print(f"❌ Backend returned an error: {e}")
        print(f"Response body: {e.response.text}")
    except Exception as e:
        print(f"❌ An unexpected error occurred while calling the backend: {e}")


if __name__ == "__main__":
    test_onboarding_flow()
