"""
Custom exceptions for the Payment Management System.
"""

from rest_framework.exceptions import APIException
from rest_framework import status


class TransactionLockedException(APIException):
    """
    Exception raised when attempting to modify a locked transaction.
    Transactions are locked when they are FULFILLED or CANCELLED.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'This transaction is locked and cannot be modified.'
    default_code = 'transaction_locked'


class InvalidStatusTransitionError(APIException):
    """
    Exception raised when attempting an invalid status transition.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Invalid status transition.'
    default_code = 'invalid_status_transition'


class InsufficientAmountError(APIException):
    """
    Exception raised when trying to use more than the available amount.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Insufficient amount available for this transaction.'
    default_code = 'insufficient_amount'


class DuplicateTransactionError(APIException):
    """
    Exception raised when attempting to create a duplicate transaction.
    """
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'A transaction with this identifier already exists.'
    default_code = 'duplicate_transaction'


class GatewayNotFoundError(APIException):
    """
    Exception raised when a payment gateway is not found.
    """
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = 'Payment gateway not found.'
    default_code = 'gateway_not_found'
