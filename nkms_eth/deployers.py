from abc import ABC, abstractmethod
from typing import Tuple

from nkms_eth.config import NuCypherMinerConfig, NuCypherTokenConfig
from .blockchain import TheBlockchain


class ContractDeployer(ABC):

    _contract_name = NotImplemented

    class ContractDeploymentError(Exception):
        pass

    def __init__(self, blockchain: TheBlockchain):
        self.__armed = False
        self._contract = None
        self.deployment_receipt = None

        # Sanity check
        if not isinstance(blockchain, TheBlockchain):
            error = 'Only TheBlockchain can be used to create a deployer, got {}.'
            raise ValueError(error.format(type(blockchain)))
        self.blockchain = blockchain

    @property
    def contract_address(self) -> str:
        try:
            address = self._contract.address
        except AttributeError:
            cls = self.__class__
            raise cls.ContractDeploymentError('Contract not deployed')
        else:
            return address

    @property
    def is_deployed(self) -> bool:
        return bool(self._contract is not None)

    @property
    def is_armed(self) -> bool:
        return bool(self.__armed is True)

    def _ensure_contract_deployment(self) -> None:
        """Raises ContractDeploymentError if the contract has not been armed and deployed."""

        if self._contract is None:
            class_name = self.__class__.__name__
            message = '{} contract is not deployed. Arm, then deploy.'.format(class_name)
            raise self.ContractDeploymentError(message)

        # http: // populus.readthedocs.io / en / latest / chain.contracts.html  # checking-availability-of-contracts
        available = bool(self.blockchain._chain.provider.are_contract_dependencies_available(self._contract_name))
        if not available:
            raise self.ContractDeploymentError('Contract is not available')

    def arm(self) -> None:
        """Safety mechanism for ethereum contract deployment"""

        if self.__armed is True:
            raise self.ContractDeploymentError("Deployer already armed, use .deploy() to deploy.")

        # Check that the contract can be deployed
        is_ready = bool(self.blockchain._chain.provider.are_contract_dependencies_available(self._contract_name))

        # If the blockchain network is public, prompt the user
        if self.blockchain._network not in self.blockchain.test_chains:
            message = """
            Are you sure you want to deploy {} on the {} network?
            
            Type "I UNDERSTAND" to arm the deployer.
            """

            answer = input(message.format(self._contract_name, self.blockchain._network))
            if answer == "I UNDERSTAND":
                arm = True
                outcome_message = '{} is armed!'.format(self.__class__.__name__)
            else:
                arm = False
                outcome_message = '{} was not armed.'.format(self.__class__.__name__)

            print(outcome_message)
        else:
            # If this is a private chain, just arm the deployer without interaction.
            arm = True

        self.__armed = arm
        return

    @abstractmethod
    def deploy(self) -> str:
        raise NotImplementedError


class NuCypherKMSTokenDeployer(ContractDeployer, NuCypherTokenConfig):

    _contract_name = 'NuCypherKMSToken'

    def __init__(self, blockchain):
        super().__init__(blockchain=blockchain)
        self._creator = self.blockchain._chain.web3.eth.accounts[0]

    def deploy(self) -> str:
        """
        Deploy and publish the NuCypherKMS Token contract
        to the blockchain network specified in self.blockchain.network.

        The contract must be armed before it can be deployed.
        Deployment can only ever be executed exactly once!
        """

        if self.is_armed is False:
            raise self.ContractDeploymentError('use .arm() to arm the contract, then .deploy().')

        if self.is_deployed is True:
            class_name = self.__class__.__name__
            message = '{} contract already deployed, use .get() to retrieve it.'.format(class_name)
            raise self.ContractDeploymentError(message)

        the_nucypher_token_contract, deployment_txhash = self.blockchain._chain.provider.deploy_contract(
            self._contract_name,
            deploy_args=[self.saturation],
            deploy_transaction={'from': self._creator})

        self.blockchain.wait_for_receipt(deployment_txhash)
        self._contract = the_nucypher_token_contract
        self.deployment_receipt = deployment_txhash

        return self.deployment_receipt


class MinerEscrowDeployer(ContractDeployer, NuCypherMinerConfig):
    """
    Deploys the MinerEscrow ethereum contract to the blockchain.  Depends on NuCypherTokenAgent
    """

    _contract_name = 'MinersEscrow'

    def __init__(self, token_agent):
        super().__init__(blockchain=token_agent.blockchain)
        self.token_agent = token_agent

    def deploy(self) -> Tuple[str, str, str]:
        """
        Deploy and publish the NuCypherKMS Token contract
        to the blockchain network specified in self.blockchain.network.

        The contract must be armed before it can be deployed.
        Deployment can only ever be executed exactly once!

        Returns transaction hashes in a tuple: deploy, reward, and initialize.
        """

        if self.is_armed is False:
            raise self.ContractDeploymentError('use .arm() to arm the contract, then .deploy().')

        if self.is_deployed is True:
            class_name = self.__class__.__name__
            message = '{} contract already deployed, use .get() to retrieve it.'.format(class_name)
            raise self.ContractDeploymentError(message)

        deploy_args = [self.token_agent.contract_address] + self.mining_coefficient
        deploy_tx = {'from': self.token_agent.origin}

        the_escrow_contract, deploy_txhash = self.blockchain._chain.provider.deploy_contract(self._contract_name,
                                                                                             deploy_args=deploy_args,
                                                                                             deploy_transaction=deploy_tx)

        self.blockchain.wait_for_receipt(deploy_txhash)
        self._contract = the_escrow_contract

        reward_txhash = self.token_agent.transact({'from': self.token_agent.origin}).transfer(self.contract_address,
                                                                                              self.reward)
        self.blockchain.wait_for_receipt(reward_txhash)

        init_txhash = self._contract.transact({'from': self.token_agent.origin}).initialize()
        self.blockchain.wait_for_receipt(init_txhash)

        self.deployment_receipt = deploy_txhash

        return deploy_txhash, reward_txhash, init_txhash


class PolicyManagerDeployer(ContractDeployer):
    """
    Depends on MinerAgent and NuCypherTokenAgent
    """

    _contract_name = 'PolicyManager'

    def __init__(self, miner_agent):
        self.token_agent = miner_agent.token_agent
        self.miner_agent = miner_agent
        super().__init__(blockchain=self.token_agent.blockchain)

    def deploy(self) -> Tuple[str, str]:
        if self.is_armed is False:
            raise self.ContractDeploymentError('PolicyManager contract not armed')
        if self.is_deployed is True:
            raise self.ContractDeploymentError('PolicyManager contract already deployed')

        # Creator deploys the policy manager
        the_policy_manager_contract, deploy_txhash = self.blockchain._chain.provider.deploy_contract(
            self._contract_name,
            deploy_args=[self.miner_agent.contract_address],
            deploy_transaction={'from': self.token_agent.origin})

        self._contract = the_policy_manager_contract

        policy_setter_txhash = self.miner_agent.transact({'from': self.token_agent.origin}).setPolicyManager(the_policy_manager_contract.address)
        self.blockchain.wait_for_receipt(policy_setter_txhash)
        self.deployment_receipt = deploy_txhash

        return deploy_txhash, policy_setter_txhash