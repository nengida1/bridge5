from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware  # Necessary for POA chains
from eth_account import Account
from eth_account.messages import encode_defunct
from datetime import datetime
import json
import pandas as pd


def connect_to(chain):
    if chain == 'source':  # The source contract chain is avax
        api_url = "https://api.avax-test.network/ext/bc/C/rpc"  # AVAX C-chain testnet
    elif chain == 'destination':  # The destination contract chain is bsc
        api_url = "https://data-seed-prebsc-1-s1.binance.org:8545/"  # BSC testnet
    else:
        raise ValueError(f"Invalid chain: {chain}")

    w3 = Web3(Web3.HTTPProvider(api_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain, contract_info):
    """
    Load the contract_info file into a dictionary.
    This function is used by the autograder and will likely be useful to you.
    """
    try:
        with open(contract_info, 'r') as f:
            contracts = json.load(f)
    except Exception as e:
        print(f"Failed to read contract info\nPlease contact your instructor\n{e}")
        return 0
    return contracts[chain]


def sign_message(token, recipient, amount, private_key):
    """
    Sign the bridge message using the warden private key.
    Assumes the Solidity side verifies a signature over:
    keccak256(abi.encodePacked(token, recipient, amount))
    """
    msg_hash = Web3.solidity_keccak(
        ['address', 'address', 'uint256'],
        [
            Web3.to_checksum_address(token),
            Web3.to_checksum_address(recipient),
            int(amount)
        ]
    )

    signed_message = Account.sign_message(
        encode_defunct(msg_hash),
        private_key=private_key
    )

    return signed_message.signature


def send_transaction(w3, function_call, sender_address, private_key):
    """
    Build, sign, send, and wait for a transaction receipt.
    """
    nonce = w3.eth.get_transaction_count(sender_address)
    gas_price = w3.eth.gas_price
    chain_id = w3.eth.chain_id

    tx = function_call.build_transaction({
        'from': sender_address,
        'nonce': nonce,
        'gas': 500000,
        'gasPrice': gas_price,
        'chainId': chain_id
    })

    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return receipt


def scan_blocks(chain, contract_info="contract_info.json"):
    """
    chain - (string) should be either "source" or "destination"

    Scan the last 5 blocks of the source and destination chains.
    Look for 'Deposit' events on the source chain and 'Unwrap' events on the destination chain.

    When Deposit events are found on the source chain, call the 'wrap' function on the destination chain.
    When Unwrap events are found on the destination chain, call the 'withdraw' function on the source chain.
    """

    if chain not in ['source', 'destination']:
        print(f"Invalid chain: {chain}")
        return 0

    source_info = get_contract_info('source', contract_info)
    destination_info = get_contract_info('destination', contract_info)

    w3_source = connect_to('source')
    w3_destination = connect_to('destination')

    source_contract = w3_source.eth.contract(
        address=Web3.to_checksum_address(source_info['address']),
        abi=source_info['abi']
    )

    destination_contract = w3_destination.eth.contract(
        address=Web3.to_checksum_address(destination_info['address']),
        abi=destination_info['abi']
    )

    private_key = source_info['private_key']
    sender_address = Account.from_key(private_key).address

    if chain == 'source':
        latest_block = w3_source.eth.block_number
        from_block = max(0, latest_block - 5)
        to_block = latest_block

        try:
            deposit_events = source_contract.events.Deposit().get_logs(
                from_block=from_block,
                to_block=to_block
            )
        except Exception as e:
            print(f"Error reading Deposit events: {e}")
            return 0

        for event in deposit_events:
            try:
                token = event['args']['token']
                recipient = event['args']['recipient']
                amount = event['args']['amount']

                signature = sign_message(token, recipient, amount, private_key)

                receipt = send_transaction(
                    w3_destination,
                    destination_contract.functions.wrap(
                        Web3.to_checksum_address(token),
                        Web3.to_checksum_address(recipient),
                        int(amount),
                        signature
                    ),
                    sender_address,
                    private_key
                )

                print(f"wrap() transaction sent: {receipt.transactionHash.hex()}")

            except Exception as e:
                print(f"Error processing Deposit event: {e}")

    elif chain == 'destination':
        latest_block = w3_destination.eth.block_number
        from_block = max(0, latest_block - 5)
        to_block = latest_block

        try:
            unwrap_events = destination_contract.events.Unwrap().get_logs(
                from_block=from_block,
                to_block=to_block
            )
        except Exception as e:
            print(f"Error reading Unwrap events: {e}")
            return 0

        for event in unwrap_events:
            try:
                token = event['args']['token']
                recipient = event['args']['recipient']
                amount = event['args']['amount']

                signature = sign_message(token, recipient, amount, private_key)

                receipt = send_transaction(
                    w3_source,
                    source_contract.functions.withdraw(
                        Web3.to_checksum_address(token),
                        Web3.to_checksum_address(recipient),
                        int(amount),
                        signature
                    ),
                    sender_address,
                    private_key
                )

                print(f"withdraw() transaction sent: {receipt.transactionHash.hex()}")

            except Exception as e:
                print(f"Error processing Unwrap event: {e}")


if __name__ == "__main__":
    scan_blocks("source")
    scan_blocks("destination")
