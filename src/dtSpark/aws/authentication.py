"""
AWS authentication module for handling SSO login.

This module provides functionality for:
- AWS SSO authentication
- Session credential management
- Profile configuration
"""

import boto3
import logging
import subprocess
from typing import Optional
from botocore.config import Config
from botocore.exceptions import ClientError, ProfileNotFound, NoCredentialsError


class AWSAuthenticator:
    """Handles AWS authentication via SSO or API keys."""

    def __init__(self, profile_name: Optional[str] = None, region: Optional[str] = None,
                 bedrock_request_timeout: int = 300,
                 access_key_id: Optional[str] = None,
                 secret_access_key: Optional[str] = None,
                 session_token: Optional[str] = None):
        """
        Initialise the AWS authenticator.

        Args:
            profile_name: AWS SSO profile name (defaults to 'default')
            region: AWS region (defaults to us-east-1)
            bedrock_request_timeout: Timeout in seconds for Bedrock Runtime requests (defaults to 300 seconds / 5 minutes)
            access_key_id: AWS access key ID (for API key authentication)
            secret_access_key: AWS secret access key (for API key authentication)
            session_token: AWS session token (optional, for temporary credentials)
        """
        self.profile_name = profile_name or 'default'
        self.region = region or 'us-east-1'
        self.bedrock_request_timeout = bedrock_request_timeout
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.session_token = session_token
        self.session = None
        self._credentials_valid = False
        self._auth_method = None  # Track which method was used: 'api_keys' or 'sso'

    def authenticate(self) -> bool:
        """
        Authenticate with AWS using API keys or SSO profile.

        Priority:
        1. If API keys are provided, use them
        2. Otherwise, use SSO profile

        Returns:
            True if authentication successful, False otherwise
        """
        # Check if API keys are provided
        if self.access_key_id and self.secret_access_key:
            return self._authenticate_with_api_keys()
        else:
            return self._authenticate_with_sso()

    def _authenticate_with_api_keys(self) -> bool:
        """
        Authenticate using AWS API keys.

        Returns:
            True if authentication successful, False otherwise
        """
        try:
            logging.info("Attempting authentication with API keys")

            # Create a session with explicit credentials
            self.session = boto3.Session(
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                aws_session_token=self.session_token,  # Optional, may be None
                region_name=self.region
            )

            # Test credentials by making a simple API call
            sts_client = self.session.client('sts')
            identity = sts_client.get_caller_identity()

            logging.info(f"Successfully authenticated with API keys as: {identity['Arn']}")
            logging.info(f"Account ID: {identity['Account']}")
            self._credentials_valid = True
            self._auth_method = 'api_keys'
            return True

        except NoCredentialsError:
            logging.error("Invalid AWS credentials (API keys)")
            logging.error("Please check your access key ID and secret access key")
            return False

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'InvalidClientTokenId':
                logging.error("Invalid AWS access key ID")
            elif error_code == 'SignatureDoesNotMatch':
                logging.error("Invalid AWS secret access key")
            elif error_code == 'ExpiredToken':
                logging.error("AWS session token has expired")
                logging.error("Please obtain new temporary credentials")
            else:
                logging.error(f"AWS authentication with API keys failed: {e}")
            return False

        except Exception as e:
            logging.error(f"Unexpected error during API key authentication: {e}")
            return False

    def _authenticate_with_sso(self) -> bool:
        """
        Authenticate using AWS SSO profile.

        Returns:
            True if authentication successful, False otherwise
        """
        try:
            logging.info(f"Attempting authentication with SSO profile '{self.profile_name}'")

            # Create a session with the specified profile
            self.session = boto3.Session(
                profile_name=self.profile_name,
                region_name=self.region
            )

            # Test credentials by making a simple API call
            sts_client = self.session.client('sts')
            identity = sts_client.get_caller_identity()

            logging.info(f"Successfully authenticated with SSO as: {identity['Arn']}")
            logging.info(f"Account ID: {identity['Account']}")
            self._credentials_valid = True
            self._auth_method = 'sso'
            return True

        except ProfileNotFound:
            logging.error(f"AWS profile '{self.profile_name}' not found")
            logging.error("Please configure your AWS SSO profile using 'aws configure sso'")
            return False

        except NoCredentialsError:
            logging.error("No AWS credentials found")
            logging.error("Please configure your AWS credentials or SSO profile")
            return False

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'ExpiredToken':
                logging.error("AWS session token has expired")
                logging.error(f"Please re-authenticate using: aws sso login --profile {self.profile_name}")
            else:
                logging.error(f"AWS authentication failed: {e}")
            return False

        except Exception as e:
            error_str = str(e)
            # Check if this is an SSO token expiration error
            if 'Token has expired' in error_str or 'refresh failed' in error_str:
                logging.warning("AWS SSO token has expired")
                logging.info("Attempting automatic re-authentication...")

                # Try to trigger SSO login automatically
                if self.trigger_sso_login():
                    logging.info("SSO login successful, retrying authentication...")
                    # Retry authentication after successful login
                    return self._authenticate_with_sso()
                else:
                    logging.error("Automatic SSO login failed")
                    logging.error(f"Please manually re-authenticate: aws sso login --profile {self.profile_name}")
                    return False
            else:
                logging.error(f"Unexpected error during authentication: {e}")
                return False

    def trigger_sso_login(self) -> bool:
        """
        Trigger AWS SSO login process by calling the AWS CLI.
        This will open the default browser for authentication.

        Returns:
            True if SSO login succeeded, False otherwise
        """
        try:
            logging.info(f"Initiating AWS SSO login for profile '{self.profile_name}'")

            # Run aws sso login command with inherited stdin/stdout/stderr
            # This allows the browser to open and the user to see the output
            result = subprocess.run(
                ['aws', 'sso', 'login', '--profile', self.profile_name],
                timeout=300  # 5 minute timeout for login process
            )

            if result.returncode == 0:
                logging.info("AWS SSO login completed successfully")
                return True
            else:
                logging.error(f"AWS SSO login failed with return code: {result.returncode}")
                return False

        except subprocess.TimeoutExpired:
            logging.error("AWS SSO login timed out")
            return False
        except FileNotFoundError:
            logging.error("AWS CLI not found. Please ensure AWS CLI is installed and in your PATH")
            return False
        except Exception as e:
            logging.error(f"Error during SSO login: {e}")
            return False

    def get_session(self) -> Optional[boto3.Session]:
        """
        Get the authenticated boto3 session.

        Returns:
            Boto3 session if authenticated, None otherwise
        """
        if not self._credentials_valid:
            logging.warning("Credentials not valid, please authenticate first")
            return None
        return self.session

    def get_client(self, service_name: str):
        """
        Get a boto3 client for a specific AWS service.

        Args:
            service_name: Name of the AWS service (e.g., 'bedrock', 's3')

        Returns:
            Boto3 client for the specified service
        """
        if not self._credentials_valid:
            raise ValueError("Not authenticated. Please call authenticate() first")

        # Configure timeouts based on service type
        # Bedrock Runtime needs longer timeouts for AI model inference (especially with tools)
        if service_name == 'bedrock-runtime':
            read_timeout = self.bedrock_request_timeout  # Configurable timeout for AI model inference
        else:
            read_timeout = 120  # 2 minutes for standard AWS services

        config = Config(
            read_timeout=read_timeout,
            connect_timeout=10,  # 10 seconds for connection
            retries={'max_attempts': 3, 'mode': 'standard'}
        )

        return self.session.client(service_name, config=config)

    def is_authenticated(self) -> bool:
        """
        Check if currently authenticated.

        Returns:
            True if authenticated, False otherwise
        """
        return self._credentials_valid

    def get_account_info(self) -> Optional[dict]:
        """
        Get information about the authenticated AWS account.

        Returns:
            Dictionary with account information or None if not authenticated
        """
        if not self._credentials_valid:
            return None

        try:
            sts_client = self.session.client('sts')
            identity = sts_client.get_caller_identity()

            return {
                'account_id': identity['Account'],
                'user_arn': identity['Arn'],
                'user_id': identity['UserId'],
                'region': self.region,
                'profile': self.profile_name,
                'auth_method': self._auth_method  # Add authentication method
            }
        except Exception as e:
            logging.error(f"Failed to retrieve account info: {e}")
            return None

    def get_auth_method(self) -> Optional[str]:
        """
        Get the authentication method used.

        Returns:
            'api_keys' or 'sso', or None if not authenticated
        """
        return self._auth_method
