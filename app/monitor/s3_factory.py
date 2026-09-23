import logging
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

class S3Factory:
    # The client's ``retries.max_attempts`` counts *retries*, so botocore makes
    # one extra attempt for the initial request -- ``botocore/args.py`` derives
    # ``total_max_attempts = max_attempts + 1``. Retry logging caps at that
    # total so the final (non-retryable) attempt is not reported as a retry.
    _MAX_RETRIES = 3
    _MAX_ATTEMPTS = _MAX_RETRIES + 1

    # Error codes that botocore's ``standard`` retry mode treats as throttling.
    # Mirrors ``botocore.retries.standard.ThrottledRetryableChecker``.
    _THROTTLED_ERROR_CODES = frozenset({
        "Throttling",
        "ThrottlingException",
        "ThrottledException",
        "RequestThrottledException",
        "TooManyRequestsException",
        "ProvisionedThroughputExceededException",
        "TransactionInProgressException",
        "RequestLimitExceeded",
        "BandwidthLimitExceeded",
        "LimitExceededException",
        "RequestThrottled",
        "SlowDown",
        "PriorRequestNotComplete",
        "EC2ThrottledException",
    })

    # Error codes botocore's ``standard`` retry mode retries as transient
    # failures. Mirrors ``botocore.retries.standard.TransientRetryableChecker``.
    _TRANSIENT_ERROR_CODES = frozenset({
        "RequestTimeout",
        "RequestTimeoutException",
        "PriorRequestNotComplete",
    })

    # HTTP status codes botocore's ``standard`` retry mode retries.
    _TRANSIENT_STATUS_CODES = frozenset({500, 502, 503, 504})

    def __init__(self, logger : logging.Logger
                ):
        """
        Docstring for __init__
        
        :param self: this instance
        :param logger: logger
        :type logger: logging.Logger
        """
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def _extract_error_details(kwargs: dict) -> tuple[str | None, int | None]:
        """Pull the error code and HTTP status out of a ``needs-retry`` event.

        The ``response`` kwarg is ``(http_response, parsed_data)``. HEAD
        responses (e.g. HeadObject) carry no body, so botocore synthesizes the
        error code from the HTTP status -- a missing object yields ``"404"``.

        :param kwargs: keyword arguments of the botocore ``needs-retry`` event
        :return: ``(error_code, status_code)``; either may be ``None``
        :rtype: tuple[str | None, int | None]
        """
        error_code: str | None = None
        status_code: int | None = None

        response = kwargs.get("response")
        if isinstance(response, tuple):
            http_response, parsed_data = response
            status_code = getattr(http_response, "status_code", None)
            if isinstance(parsed_data, dict):
                error_info = parsed_data.get("Error", {})
                if isinstance(error_info, dict):
                    error_code = error_info.get("Code")

        if error_code is None and kwargs.get("caught_exception") is not None:
            error_code = type(kwargs["caught_exception"]).__name__

        return error_code, status_code

    def _log_retry_events(self, **kwargs):
        """Log only the S3 retries that botocore actually performs.

        The ``needs-retry`` event fires for *every* response so that handlers
        can vote on the retry decision -- it does not fire only when a retry
        happens. Logging it unconditionally therefore reported benign,
        non-retryable responses (e.g. the 404 from a HEAD on a not-yet-uploaded
        object) as retries. Restrict logging to the codes/statuses that the
        configured ``standard`` retry mode retries, and only while attempts
        remain.
        """
        attempts = kwargs.get("attempts") or 1
        if attempts >= self._MAX_ATTEMPTS:
            # Final attempt: botocore will not retry, so do not claim it will.
            return

        error_code, status_code = self._extract_error_details(kwargs)

        if error_code in self._THROTTLED_ERROR_CODES:
            self.logger.warning(
                f"(!) THROTTLED: S3 requested a backoff. Code: {error_code}"
            )
            return

        if (
            error_code in self._TRANSIENT_ERROR_CODES
            or status_code in self._TRANSIENT_STATUS_CODES
        ):
            reason = error_code or f"HTTP {status_code}"
            self.logger.debug(f"Retrying S3 request due to: {reason}")
            return

        caught_exception = kwargs.get("caught_exception")
        if caught_exception is not None:
            self.logger.debug(
                f"Retrying S3 request due to: {type(caught_exception).__name__}"
            )

    def get_s3_client(self, profile_config: dict) -> "S3Client":
        """
        Docstring for get_s3_client
        
        :param self: instance of this class
        :param profile_config: Profile config is JSON field in profile as stored in the database.
        :type profile_name: dict
        :return: boto3 client
        :rtype: Any
        """

        # Get endpoint
        endpoint = profile_config.get('endpoint', "")
        # For AWS the endpoint can be derived from the region
        if not endpoint:
            region = profile_config.get('region')
            endpoint = f"s3.{region}.amazonaws.com"

        # Check if "http://" inside endpoint
        if 'http://' in endpoint:
            endpoint = endpoint.replace('http://', 'https://')

        # Check if "https://" inside endpoint
        endpoint_url = endpoint if 'https://' in endpoint else f"https://{endpoint}"
        
        access_key_id = profile_config.get('access_key_id')
        access_key_secret = profile_config.get('access_key_secret')
        region = profile_config.get('region')
        provider_name = profile_config.get('provider_name')

        # Define common client settings once
        common_config = Config(
            retries={'max_attempts': self._MAX_RETRIES, 'mode': 'standard'},
            # Optional: connect_timeout and read_timeout can be added here for extra reliability
            connect_timeout=5, 
            read_timeout=10
        )

        # On AWS we can omit the endpoint_url and use the region only

        # Built-in providers are named "Amazon AWS S3"; rclone-imported AWS
        # profiles carry the bare rclone key "AWS". Match both, plus any other
        # name containing "amazon", so native-AWS profiles take the region path.
        provider_key = (provider_name or "").strip().lower()
        is_aws = provider_key == "aws" or "amazon" in provider_key

        if is_aws:
            self.logger.debug("Provider is AWS")
            client = boto3.client(
                service_name='s3',
                aws_access_key_id=access_key_id,
                aws_secret_access_key=access_key_secret,
                region_name=region,
                config=common_config
                )
        else:
            # For Cloudflare R2, ensure region is set to 'auto' if missing
            if 'cloudflare' in provider_key and not region:
                region = 'auto'

            client = boto3.client(
                service_name='s3',
                aws_access_key_id=access_key_id,
                aws_secret_access_key=access_key_secret,
                endpoint_url=endpoint_url,
                region_name=region,
                config=common_config
            )

        # Access the internal event system
        event_system = client.meta.events
        # Register the logger to the 'needs-retry' event
        # This event fires whenever boto3 decides to retry a request
        event_system.register('needs-retry.s3.*', self._log_retry_events)
        return client

    @staticmethod
    def test_connection(profile_config: dict, logger: logging.Logger, prompt) -> None:
        """
        Test S3 connectivity by listing buckets.

        Prints results via the provided prompt service.
        """
        factory = S3Factory(logger=logger)
        s3_client = factory.get_s3_client(profile_config=profile_config)
        try:
            buckets = s3_client.list_buckets()
            if not buckets or 'Buckets' not in buckets:
                prompt.print("No buckets found on remote")
            else:
                prompt.print("Buckets:")
                for bucket in buckets["Buckets"]:
                    prompt.print(f"Bucket: {bucket}")
            prompt.print("Test successful")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'AccessDenied':
                prompt.print("Connection successful! (ListBuckets permission denied).")
                prompt.print("Your credentials are valid, but restricted.")
            else:
                prompt.print(f"Error: {e}")
                prompt.print("Test failed")
        except BotoCoreError as e:
            prompt.print(f"Error: {e}")
            prompt.print("Test failed")

