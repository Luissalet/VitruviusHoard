// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

contract Measure {
    uint256 public total;
    address private owner;

    constructor() { owner = msg.sender; }

    function read(uint256 input) external pure returns (uint256) {
        return input < 10 ? input + 128 : 0;
    }

    function store(uint256 input) external {
        require(msg.sender == owner, "owner");
        total = input;
    }

    function value() external view returns (uint256) { return total; }
    receive() external payable {}
}
