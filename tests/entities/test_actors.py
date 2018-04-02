import random

import pytest

from nkms_eth.actors import Miner
from nkms_eth.agents import MinerAgent
from nkms_eth.utilities import spawn_miners


def test_miner_locking_tokens(testerchain, mock_token_deployer, mock_miner_agent):

    mock_token_deployer._global_airdrop(amount=10000)    # weeee

    miner = Miner(miner_agent=mock_miner_agent, address=testerchain._chain.web3.eth.accounts[1])

    an_amount_of_tokens = 1000 * mock_token_deployer._M
    miner.stake(amount=an_amount_of_tokens, locktime=mock_miner_agent._deployer._min_release_periods, auto_switch_lock=False)

    # Verify that the escrow is allowed to receive tokens
    # assert mock_miner_agent.token_agent.read().allowance(miner.address, mock_miner_agent.contract_address) == 0

    # Stake starts after one period
    # assert miner.token_balance() == 0
    # assert mock_miner_agent.read().getLockedTokens(miner.address) == 0

    # Wait for it...
    testerchain.wait_time(mock_miner_agent._deployer._hours_per_period)

    assert mock_miner_agent.read().getLockedTokens(miner.address) == an_amount_of_tokens


def test_mine_then_withdraw_tokens(testerchain, mock_token_deployer, token_agent, mock_miner_agent, mock_miner_escrow_deployer):
    """
    - Airdrop tokens to everyone
    - Create a Miner (Ursula)
    - Spawn additional miners
    - All miners lock tokens
    - Wait (with time)
    - Miner (Ursula) mints new tokens
    """

    mock_token_deployer._global_airdrop(amount=10000)

    _origin, *everybody = testerchain._chain.web3.eth.accounts
    ursula_address, *everyone_else = everybody

    miner = Miner(miner_agent=mock_miner_agent, address=ursula_address)

    initial_balance = miner.token_balance()
    assert token_agent.get_balance(miner.address) == miner.token_balance()

    stake_amount = (10 + random.randrange(9000)) * mock_token_deployer._M
    miner.stake(amount=stake_amount, locktime=30, auto_switch_lock=False)

    # Stake starts after one period
    assert miner.token_balance() == 0
    assert mock_miner_agent.read().getLockedTokens(ursula_address) == 0

    # Wait for it...
    testerchain.wait_time(mock_miner_agent._deployer._hours_per_period)

    # Have other address lock tokens, and wait...
    spawn_miners(miner_agent=mock_miner_agent, addresses=everyone_else, locktime=30, m=mock_token_deployer._M)
    testerchain.wait_time(mock_miner_agent._deployer._hours_per_period*2)

    # miner.confirm_activity()
    miner.mint()
    miner.collect_reward()

    final_balance = token_agent.get_balance(miner.address)
    assert final_balance > initial_balance


def test_sample_miners(testerchain, mock_token_deployer, mock_miner_agent):
    mock_token_deployer._global_airdrop(amount=10000)

    _origin, *everyone_else = testerchain._chain.web3.eth.accounts[1:]
    spawn_miners(addresses=everyone_else, locktime=100, miner_agent=mock_miner_agent, m=mock_token_deployer._M)

    testerchain.wait_time(mock_miner_agent._deployer._hours_per_period)

    with pytest.raises(MinerAgent.NotEnoughUrsulas):
        mock_miner_agent.sample(quantity=100)  # Waay more than we have deployed

    miners = mock_miner_agent.sample(quantity=3)
    assert len(miners) == 3
    assert len(set(miners)) == 3


# def test_publish_miner_ids(testerchain, mock_token_deployer, mock_miner_agent):
#     mock_token_deployer._global_airdrop(amount=10000)    # weeee
#
#     miner_addr = testerchain._chain.web3.eth.accounts[1]
#     miner = Miner(miner_agent=mock_miner_agent, address=miner_addr)
#
#     balance = miner.token_balance()
#     miner.lock(amount=balance, locktime=1)
#
#     # Publish Miner IDs to the DHT
#     mock_miner_id = os.urandom(32)
#     _txhash = miner.publish_miner_id(mock_miner_id)
#
#     # Fetch the miner Ids
#     stored_miner_ids = miner.fetch_miner_ids()
#
#     assert len(stored_miner_ids) == 1
#     assert mock_miner_id == stored_miner_ids[0]
#
#     # Repeat, with another miner ID
#     another_mock_miner_id = os.urandom(32)
#     _txhash = miner.publish_miner_id(another_mock_miner_id)
#
#     stored_miner_ids = miner.fetch_miner_ids()
#
#     assert len(stored_miner_ids) == 2
#     assert another_mock_miner_id == stored_miner_ids[1]
#
#     # TODO change encoding when v4 of web3.py is released
#     supposedly_the_same_miner_id = mock_miner_agent.call() \
#         .getMinerInfo(mock_miner_agent._deployer.MinerInfoField.MINER_ID.value,
#                       miner_addr,
#                       1).encode('latin-1')
#
#     assert another_mock_miner_id == supposedly_the_same_miner_id
#