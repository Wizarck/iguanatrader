/**
 * Frontend mirrors of the broker-types catalogue DTOs in
 * ``apps/api/src/iguanatrader/api/routes/broker_types.py``.
 */

export type BrokerTypeOption = {
  code: string;
  label: string;
  description: string;
  required_fields: string[];
};

export type BrokerTypesResponse = {
  sec_types: BrokerTypeOption[];
  order_types: BrokerTypeOption[];
  algo_kinds: BrokerTypeOption[];
};
