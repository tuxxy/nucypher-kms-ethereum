from collections import OrderedDict
from typing import Tuple, List

from nkms_eth.escrow import MinerEscrow
from nkms_eth.miner import Miner
from nkms_eth.token import NuCypherKMSToken


class PolicyArrangement:
    """
    A relationship between Alice and a single Ursula as part of BlockchainPolicy
    """

    def __init__(self, author, miner, value: int, periods: int, arrangement_id: bytes=None):

        if arrangement_id is None:
            self.id = self.__class__._generate_arrangement_id()  # TODO: Generate policy ID

        # The relationship exists between two addresses
        self.author = author
        self.policy_agent = author.policy_agent


        self.miner = miner

        # Arrangement value, rate, and duration
        rate = value // periods
        self._rate = rate

        self.value = value
        self.periods = periods  # TODO: datetime -> duration in blocks

        self.is_published = False

    @staticmethod
    def _generate_arrangement_id(policy_hrac: bytes) -> bytes:
        pass  # TODO

    def __repr__(self):
        class_name = self.__class__.__name__
        r = "{}(client={}, node={})"
        r = r.format(class_name, self.author, self.miner)
        return r

    def publish(self, gas_price: int) -> str:

        payload = {'from': self.author.address,
                   'value': self.value,
                   'gas_price': gas_price}


        txhash = self.policy_agent.transact(payload).createPolicy(self.id,
                                                                  self.miner.address,
                                                                  self.periods)

        self.policy_agent._blockchain._chain.wait.for_receipt(txhash)

        self.publish_transaction = txhash
        self.is_published = True
        return txhash

    def __update_periods(self) -> None:
        blockchain_record = self.policy_agent.fetch_arrangement_data(self.id)
        client, delegate, rate, *periods = blockchain_record
        self._elapsed_periods = periods

    def revoke(self, gas_price: int) -> str:
        """Revoke this arrangement and return the transaction hash as hex."""
        txhash = self.policy_agent.revoke_arrangement(self.id, author=self.author, gas_price=gas_price)
        self.revoke_transaction = txhash
        return txhash


class PolicyManager:

    __contract_name = 'PolicyManager'

    class ContractDeploymentError(Exception):
        pass

    def __init__(self, escrow: MinerEscrow):
        self.escrow = escrow
        self.token = escrow.token
        self.blockchain = self.token.blockchain

        self.armed = False
        self._contract = None

    @property
    def is_deployed(self):
        return bool(self._contract is not None)

    def arm(self) -> None:
        self.armed = True

    def deploy(self) -> Tuple[str, str]:
        if self.armed is False:
            raise PolicyManager.ContractDeploymentError('PolicyManager contract not armed')
        if self.is_deployed is True:
            raise PolicyManager.ContractDeploymentError('PolicyManager contract already deployed')
        if self.escrow._contract is None:
            raise MinerEscrow.ContractDeploymentError('Escrow contract must be deployed before')
        if self.token.contract is None:
            raise NuCypherKMSToken.ContractDeploymentError('Token contract must be deployed before')

        # Creator deploys the policy manager
        the_policy_manager_contract, deploy_txhash = self.blockchain._chain.provider.deploy_contract(
            self.__contract_name,
            deploy_args=[self.escrow._contract.address],
            deploy_transaction={'from': self.token.creator})

        self._contract = the_policy_manager_contract

        set_txhash = self.escrow.transact({'from': self.token.creator}).setPolicyManager(the_policy_manager_contract.address)
        self.blockchain._chain.wait.for_receipt(set_txhash)

        return deploy_txhash, set_txhash

    def __call__(self, *args, **kwargs):
        return self._contract.call()

    @classmethod
    def get(cls, escrow: MinerEscrow) -> 'PolicyManager':
        contract = escrow.blockchain._chain.provider.get_contract(cls.__contract_name)
        instance = cls(escrow)
        instance._contract = contract
        return instance

    def transact(self, *args):
        """Transmit a network transaction."""
        return self._contract.transact(*args)

    def fetch_arrangement_data(self, arrangement_id: bytes) -> list:
        blockchain_record = self.__call__().policies(arrangement_id)
        return blockchain_record

    def revoke_arrangement(self, arrangement_id: bytes, author: 'PolicyAuthor', gas_price: int):
        """
        Revoke by arrangement ID; Only the policy author can revoke the policy
        """
        txhash = self.transact({'from': author.address, 'gas_price': gas_price}).revokePolicy(arrangement_id)
        self.blockchain._chain.wait.for_receipt(txhash)
        return txhash


class PolicyAuthor:
    def __init__(self, address: bytes, policy_manager: PolicyManager):

        if policy_manager.is_deployed is False:
            raise PolicyManager.ContractDeploymentError('PolicyManager contract not deployed.')
        self.policy_manager = policy_manager

        if isinstance(address, bytes):
            address = address.hex()
        self.address = address

        self._arrangements = OrderedDict()    # Track authored policies by id

    def make_arrangement(self, miner: Miner, periods: int, rate: int, arrangement_id: bytes=None) -> PolicyArrangement:
        """
        Create a new arrangement to carry out a blockchain policy for the specified rate and time.
        """

        value = rate * periods
        arrangement = PolicyArrangement(author=self,
                                        miner=miner,
                                        value=value,
                                        periods=periods)

        self._arrangements[arrangement.id] = {arrangement_id: arrangement}
        return arrangement

    def get_arrangement(self, arrangement_id: bytes) -> PolicyArrangement:
        """Fetch a published arrangement from the blockchain"""

        blockchain_record = self.policy_manager().policies(arrangement_id)
        author_address, miner_address, rate, start_block, end_block, downtime_index = blockchain_record

        duration = end_block - start_block

        miner = Miner(address=miner_address, escrow=self.policy_manager.escrow)
        arrangement = PolicyArrangement(author=self, miner=miner, periods=duration, rate=rate)

        arrangement.is_published = True
        return arrangement

    def revoke_arrangement(self, arrangement_id):
        """Lookup the arrangement in the cache and revoke it on the blockchain"""
        try:
            arrangement = self._arrangements[arrangement_id]
        except KeyError:
            raise Exception('No such arrangement')
        else:
            txhash = arrangement.revoke()
        return txhash

    def select_miners(self, quantity: int) -> List[str]:
        miner_addresses = self.policy_manager.escrow.sample(quantity=quantity)
        return miner_addresses

    def balance(self):
        return self.policy_manager.token().balanceOf(self.address)

    def revoke(self, gas_price: int) -> str:
        """Revoke this arrangement and return the transaction hash as hex."""

        txhash = self.policy_agent.revoke_arrangement(self.id, author=self.author, gas_price=gas_price)
        self.revoke_transaction = txhash

        return txhash


class BlockchainPolicy:
    """A collection of n BlockchainArrangements representing a single Policy"""

    def __init__(self):
        self._arrangements = list()
