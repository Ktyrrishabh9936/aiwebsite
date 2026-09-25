# Apartment inventory and CRM sales

The saleable item is a flat. The apartment project contains towers; each tower
contains uniquely numbered flats. The existing three-step setup remains:

1. Project details: name, location, builder/owner and optional default price.
2. Property type: residential apartment project.
3. Inventory: tower, BHK, count, first flat number, number increment and price range.

For example, Tower A, 2 BHK, count 4, first number 101 and increment 1 creates
101, 102, 103, 104. An increment of 100 creates 101, 201, 301, 401. Prefixes and
leading zeroes are preserved. Multiple rows can describe the same BHK in a
tower when their number sequences do not overlap. Up to 100 rows / 5,000 flats
can be generated per project.

Every generated flat receives the group's price range and starts with the
minimum as its asking price. Manage flats allows a separate price override,
filtering by tower/BHK/status, and sale or rent listing. Regeneration preserves
unit IDs, manually overridden prices and transaction history. Existing unit
numbers cannot be removed by changing a group: use Inactive to withdraw a flat.

## Linking and closing

In CRM choose apartment, tower and flat. The opportunity records the exact
unit, listing version, and agreed amount. Linking expresses buyer interest;
it does not reserve the unit. Multiple interested leads can select a flat,
but the atomic availability check permits only one successful closing.

Convert Lead, or changing a linked real estate lead to Won, marks the unit Sold
(or Rented for a rental listing) and records the agreed amount and lead ID.
The project itself stays active. The inventory history records each completed
transaction. It is an internal CRM closing record, not proof of a registered
sale deed. Reserved is a manual hold; release it to Available before closing.

Relist for sale or rent opens a new listing cycle. Earlier sale and rental
history remains visible. An uncompleted opportunity from a previous listing
cannot close a new listing; select the flat again to obtain current terms.
Repeating an already completed conversion does not create another unit sale.

## Existing projects

Old count-only apartment projects are preserved. Use **Set flat numbers & prices**
to supply numbering and create unit records. The system does not invent flat
numbers for existing projects. Old unconverted project-level opportunities
must be replaced with a flat selection. Completed historical opportunities
are retained without guessing which flat was purchased.

## Future partner access and AI generation

Projects and units have stable workspace IDs and unit records reserve
`assigned_to_user_ids` for membership-based allocations. Agent/channel-partner
assignment UI and access enforcement are not enabled yet: these should use the
planned workspace membership/permissions service. An allocation should reference
the same unit, never create a duplicate saleable copy. Project/tower allocations
can expand to units, while a shared availability record prevents double sales.

An AI assistant can later produce the same validated inventory setup payload for
human review; numbering validation and the normal property API should remain the
only write path. No AI generator or partner portal is included in this change.

## Research basis

- [U.P. RERA project registration SOP](https://www.up-rera.in/pdf/66909SOP_Project_Registration.pdf)
  describes tower-wise inventory including unit number, floor and area, and review
  of imported inventory before completion.
- [MahaRERA project updates](https://maharera.maharashtra.gov.in/index.php/guidance-project-update-quarterly-annually)
  distinguish building-level apartment counts booked, sold and allotted.

These sources informed the hierarchy and lifecycle. This module does not submit
regulatory returns or implement a legal conveyancing workflow.
