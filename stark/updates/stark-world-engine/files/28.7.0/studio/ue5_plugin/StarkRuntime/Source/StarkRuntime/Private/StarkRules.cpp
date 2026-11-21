// Stark World Engine Runtime - game rules. Same behaviour as the Stark World Engine browser engine (Game.prototype in ENGINE_JS) and
// the Godot runtime (godot_addon/stark_runtime/core/*.gd).
#include "StarkRules.h"

void UStarkRules::Setup(const FStarkGameDef& InDef)
{
	Def = InDef;
	Difficulty = Def.Rules.Difficulty.IsEmpty() ? TEXT("normal") : Def.Rules.Difficulty;
}

void UStarkRules::NewGame()
{
	Hp = (float)FMath::Max(1, Def.Rules.PlayerHp);
	Lvl = 1;
	Xp = Gold = Score = 0;
	Inventory.Reset();
	Equipped.Reset();
	Quests.Reset();
	Gone.Reset();
	Flags.Reset();
	Cooldowns.Reset();
	LevelIndex = 0;
	bWon = false;
	CheckpointLevel = -1;
	Difficulty = Def.Rules.Difficulty.IsEmpty() ? TEXT("normal") : Def.Rules.Difficulty;
	CloseDialogue();
	for (const FString& Id : Def.Rules.StartItems)
	{
		Give(Id, 1, true);
	}
}

// ---------------------------------------------------------------- data
const FStarkQuestDef* UStarkRules::FindQuest(const FString& Id) const
{
	return Def.Quests.FindByPredicate([&Id](const FStarkQuestDef& Q) { return Q.Id == Id; });
}

const FStarkDialogueDef* UStarkRules::FindDialogue(const FString& Id) const
{
	return Def.Dialogues.FindByPredicate([&Id](const FStarkDialogueDef& D) { return D.Id == Id; });
}

const FStarkEnemyDef* UStarkRules::FindEnemy(const FString& Kind) const
{
	const FStarkEnemyDef* E = Def.Enemies.FindByPredicate([&Kind](const FStarkEnemyDef& D) { return D.Kind == Kind; });
	return E ? E : Def.Enemies.FindByPredicate([](const FStarkEnemyDef& D) { return D.Kind == TEXT("grunt"); });
}

const FStarkLevelDef* UStarkRules::FindLevel(int32 Index) const
{
	return Def.Levels.IsValidIndex(Index) ? &Def.Levels[Index] : nullptr;
}

FStarkItemDef UStarkRules::GetItem(const FString& Id) const
{
	if (const FStarkItemDef* It = Def.Items.FindByPredicate([&Id](const FStarkItemDef& I) { return I.Id == Id; }))
	{
		return *It;
	}
	FStarkItemDef Unknown;
	Unknown.Id = Id;
	Unknown.Name = Id.Replace(TEXT("_"), TEXT(" "));
	Unknown.Kind = TEXT("quest");
	return Unknown;
}

FString UStarkRules::NpcName(const FString& Id) const
{
	const FStarkNpcDef* N = Def.Npcs.FindByPredicate([&Id](const FStarkNpcDef& D) { return D.Id == Id; });
	return N ? N->Name : (Id.IsEmpty() ? TEXT("someone") : Id);
}

FString UStarkRules::EnemyName(const FString& Id) const
{
	for (const FStarkLevelDef& L : Def.Levels)
	{
		for (const FStarkObjectDef& O : L.Objects)
		{
			if (O.Type == TEXT("enemy") && O.Id == Id)
			{
				return O.Name.IsEmpty() ? Id : O.Name;
			}
		}
	}
	return NpcName(Id);
}

bool UStarkRules::IsMinor(const FString& Id, const FString& Age) const
{
	if (!Age.IsEmpty() && Age != TEXT("adult")) { return true; }
	if (Id.IsEmpty()) { return false; }
	if (Def.Minors.Contains(Id)) { return true; }
	const FStarkNpcDef* N = Def.Npcs.FindByPredicate([&Id](const FStarkNpcDef& D) { return D.Id == Id; });
	return N && !N->Age.IsEmpty() && N->Age != TEXT("adult");
}

float UStarkRules::HpMul() const
{
	const FStarkDifficultyDef* D = Def.Rules.Difficulties.FindByPredicate([this](const FStarkDifficultyDef& X) { return X.Name == Difficulty; });
	return D ? D->HpMul : 1.f;
}

float UStarkRules::DmgMul() const
{
	const FStarkDifficultyDef* D = Def.Rules.Difficulties.FindByPredicate([this](const FStarkDifficultyDef& X) { return X.Name == Difficulty; });
	return D ? D->DmgMul : 1.f;
}

float UStarkRules::TerrainHeight(int32 LevelIdx, float X, float Z) const
{
	const FStarkLevelDef* L = FindLevel(LevelIdx);
	if (!L || L->Mode == TEXT("2d"))
	{
		return 0.f;
	}
	const double S = L->Seed;
	const double V = FMath::Sin(X * 0.13 + S) * 0.6 + FMath::Cos(Z * 0.11 + S * 0.7) * 0.6 + FMath::Sin((X + Z) * 0.05 + S) * 0.8
		+ FMath::Cos(X * 0.045 - Z * 0.06 + S * 0.4) * 0.9 + FMath::Sin(X * 0.29 + Z * 0.23 + S * 1.3) * 0.18;
	double H = L->Amp * V * 0.55;
	const double D = FMath::Max(FMath::Abs(X), FMath::Abs(Z)) - L->Size;
	if (D > 0.0)
	{
		const double T = FMath::Min(1.0, D / FMath::Max(1.0, (double)L->Margin));
		H += L->Edge * T * T * (3.0 - 2.0 * T);
	}
	return (float)H;
}

float UStarkRules::WaterDepth(int32 LevelIdx, float X, float Z) const
{
	const FStarkLevelDef* L = FindLevel(LevelIdx);
	return (L && L->HasWater) ? L->Water - TerrainHeight(LevelIdx, X, Z) : -9.f;
}

void UStarkRules::Toast(const FString& Message, const FString& Kind)
{
	PendingToasts.Emplace(Message, Kind);
}

// ---------------------------------------------------------------- inventory + stats
int32 UStarkRules::Count(const FString& Id) const
{
	const int32* N = Inventory.Find(Id);
	return N ? *N : 0;
}

bool UStarkRules::Has(const FString& Id, int32 N) const
{
	return Count(Id) >= FMath::Max(1, N);
}

void UStarkRules::Give(const FString& Id, int32 N, bool bQuiet)
{
	N = FMath::Max(1, N);
	const FStarkItemDef It = GetItem(Id);
	if (It.Kind == TEXT("treasure") && It.Gold > 0)
	{
		Gold += It.Gold * N;
		if (!bQuiet) { Toast(FString::Printf(TEXT("+%d gold (%s)"), It.Gold * N, *It.Name)); }
		return;
	}
	Inventory.FindOrAdd(Id) += N;
	if (!bQuiet) { Toast(N > 1 ? FString::Printf(TEXT("+ %s x%d"), *It.Name, N) : FString::Printf(TEXT("+ %s"), *It.Name)); }
	if (It.Kind == TEXT("equip") && !Equipped.Contains(It.Slot))
	{
		Equipped.Add(It.Slot, Id);
		if (!bQuiet) { Toast(TEXT("Equipped ") + It.Name, TEXT("l")); }
	}
	FStarkEvent E;
	E.Item = Id;
	E.N = N;
	Event(TEXT("collect"), E);
}

bool UStarkRules::Take(const FString& Id, int32 N)
{
	N = FMath::Max(1, N);
	if (!Has(Id, N)) { return false; }
	int32& C = Inventory.FindOrAdd(Id);
	C -= N;
	if (C <= 0)
	{
		Inventory.Remove(Id);
		TArray<FString> Slots;
		for (const TPair<FString, FString>& P : Equipped) { if (P.Value == Id) { Slots.Add(P.Key); } }
		for (const FString& S : Slots) { Equipped.Remove(S); }
	}
	return true;
}

void UStarkRules::UseItem(const FString& Id)
{
	if (!Has(Id)) { return; }
	const FStarkItemDef It = GetItem(Id);
	if (It.Kind == TEXT("consumable"))
	{
		const int32 Mx = Stats().MaxHp;
		if (Hp >= Mx) { Toast(TEXT("Already at full health")); return; }
		Take(Id, 1);
		const int32 Heal = FMath::Max(1, It.Heal);
		Hp = FMath::Min((float)Mx, Hp + Heal);
		Toast(FString::Printf(TEXT("%s: +%d HP"), *It.Name, Heal), TEXT("l"));
	}
	else if (It.Kind == TEXT("equip"))
	{
		const FString* Cur = Equipped.Find(It.Slot);
		if (Cur && *Cur == Id) { Equipped.Remove(It.Slot); Toast(TEXT("Unequipped ") + It.Name); }
		else { Equipped.Add(It.Slot, Id); Toast(TEXT("Equipped ") + It.Name, TEXT("l")); }
		Hp = FMath::Min(Hp, (float)Stats().MaxHp);
	}
}

void UStarkRules::Quaff()
{
	FString Best;
	int32 BestHeal = TNumericLimits<int32>::Max();
	for (const TPair<FString, int32>& P : Inventory)
	{
		const FStarkItemDef It = GetItem(P.Key);
		if (It.Kind == TEXT("consumable") && It.Heal < BestHeal) { Best = P.Key; BestHeal = It.Heal; }
	}
	if (Best.IsEmpty()) { Toast(TEXT("No potions")); } else { UseItem(Best); }
}

FStarkStats UStarkRules::Stats() const
{
	FStarkStats S;
	int32 Atk = 1 + (Lvl - 1) / 2;
	int32 DefV = 0;
	int32 MaxHp = Def.Rules.PlayerHp + (Lvl - 1);
	float Spd = 1.f;
	for (const TPair<FString, FString>& P : Equipped)
	{
		const FStarkItemDef It = GetItem(P.Value);
		Atk += It.Atk;
		DefV += It.Def;
		MaxHp += It.Hp;
		if (It.Speed > 0.f) { Spd *= It.Speed; }
	}
	S.Atk = FMath::Max(1, Atk);
	S.Def = DefV;
	S.MaxHp = FMath::Max(1, MaxHp);
	S.Speed = FMath::Clamp(Spd, 0.2f, 4.f);
	return S;
}

int32 UStarkRules::XpNeed() const
{
	return FMath::RoundToInt(Def.Rules.XpBase * FMath::Pow((float)Lvl, Def.Rules.XpPow));
}

void UStarkRules::AddXp(int32 N)
{
	Xp += N;
	Score += N;
	int32 Need = XpNeed();
	while (Xp >= Need)
	{
		Xp -= Need;
		++Lvl;
		Hp = (float)Stats().MaxHp;
		Toast(FString::Printf(TEXT("Level up! You are now level %d"), Lvl), TEXT("l"));
		for (const FStarkAbilityDef& A : Def.Rules.Abilities)
		{
			if (A.Level == Lvl) { Toast(FString::Printf(TEXT("New ability: %s (%s)"), *A.Name, *A.Key), TEXT("q")); }
		}
		Need = XpNeed();
	}
}

bool UStarkRules::Hurt(float Damage)
{
	if (bInvulnerable) { return false; }
	const float D = FMath::Max(0.5f, Damage * DmgMul() - Stats().Def * 0.5f);
	Hp = FMath::Max(0.f, Hp - D);
	if (Hp <= 0.f)
	{
		Gold = FMath::FloorToInt(Gold * Def.Rules.DeathGoldKeep);
		Hp = (float)Stats().MaxHp;
		return true;
	}
	return false;
}

bool UStarkRules::HasAbility(const FString& Name) const
{
	return Def.Rules.Abilities.ContainsByPredicate([&](const FStarkAbilityDef& A) { return A.Name == Name && Lvl >= A.Level; });
}

bool UStarkRules::UseAbility(const FString& Name)
{
	const float* Cd = Cooldowns.Find(Name);
	if (!HasAbility(Name) || (Cd && *Cd > 0.f)) { return false; }
	for (const FStarkAbilityDef& A : Def.Rules.Abilities)
	{
		if (A.Name == Name) { Cooldowns.Add(Name, A.Cooldown); }
	}
	return true;
}

void UStarkRules::TickCooldowns(float DeltaSeconds)
{
	for (TPair<FString, float>& P : Cooldowns) { P.Value = FMath::Max(0.f, P.Value - DeltaSeconds); }
}

// ---------------------------------------------------------------- quests
FString UStarkRules::QuestState(const FString& Id) const
{
	const FStarkQuestProgress* P = Quests.Find(Id);
	return P ? P->State : FString();
}

const FStarkQuestStep* UStarkRules::CurrentStep(const FStarkQuestDef& Q) const
{
	const FStarkQuestProgress* P = Quests.Find(Q.Id);
	return (P && Q.Steps.IsValidIndex(P->Step)) ? &Q.Steps[P->Step] : nullptr;
}

void UStarkRules::StartQuest(const FString& Id, bool bQuiet)
{
	const FStarkQuestDef* Q = FindQuest(Id);
	if (!Q || Quests.Contains(Id)) { return; }
	FStarkQuestProgress P;
	P.State = TEXT("active");
	Quests.Add(Id, P);
	InitStep(*Q);
	if (!bQuiet) { Toast(TEXT("New quest: ") + (Q->Title.IsEmpty() ? Id : Q->Title), TEXT("q")); }
	CheckStep(*Q);
}

void UStarkRules::InitStep(const FStarkQuestDef& Q)
{
	FStarkQuestProgress& P = Quests.FindChecked(Q.Id);
	P.N = 0;
	if (const FStarkQuestStep* S = CurrentStep(Q))
	{
		if (S->Type == TEXT("collect")) { P.N = FMath::Min(Count(S->Item), FMath::Max(1, S->Count)); }
	}
	Foes(Q);
}

void UStarkRules::Foes(const FStarkQuestDef& Q)
{
	const FStarkQuestStep* S = CurrentStep(Q);
	const FStarkQuestProgress* P = Quests.Find(Q.Id);
	if (!S || !P || S->Type != TEXT("defeat") || !S->Id.IsEmpty() || P->State != TEXT("active")) { return; }
	const int32 Lv = S->Level >= 0 ? S->Level : Q.Level;
	if (Lv == LevelIndex && EnsureFoes) { EnsureFoes(S->Kind, FMath::Max(1, S->Count) - P->N); }
}

bool UStarkRules::StepDone(const FStarkQuestDef& Q) const
{
	const FStarkQuestStep* S = CurrentStep(Q);
	const FStarkQuestProgress* P = Quests.Find(Q.Id);
	return S && P && P->N >= FMath::Max(1, S->Count);
}

void UStarkRules::CheckStep(const FStarkQuestDef& Q)
{
	FStarkQuestProgress* P = Quests.Find(Q.Id);
	if (!P || P->State != TEXT("active")) { return; }
	int32 Guard = 0;
	while (StepDone(Q) && Guard++ < 20)
	{
		const FStarkQuestStep* S = CurrentStep(Q);
		if (S->Type == TEXT("collect") && S->Consume) { Take(S->Item, FMath::Max(1, S->Count)); }
		P = Quests.Find(Q.Id);
		P->Step++;
		if (P->Step >= Q.Steps.Num()) { CompleteQuest(Q); return; }
		InitStep(Q);
		if (const FStarkQuestStep* Next = CurrentStep(Q)) { Toast(TEXT("Next: ") + StepText(*Next), TEXT("q")); }
		P = Quests.Find(Q.Id);
	}
	if (Q.Steps.Num() == 0) { CompleteQuest(Q); }
}

void UStarkRules::CompleteQuest(const FStarkQuestDef& Q)
{
	FStarkQuestProgress* P = Quests.Find(Q.Id);
	if (!P || P->State == TEXT("done")) { return; }
	P->State = TEXT("done");
	Toast(TEXT("Quest complete: ") + (Q.Title.IsEmpty() ? Q.Id : Q.Title), TEXT("q"));
	if (Q.Reward.Gold > 0) { Gold += Q.Reward.Gold; Toast(FString::Printf(TEXT("+%d gold"), Q.Reward.Gold)); }
	for (const FString& It : Q.Reward.Items) { Give(It, 1); }
	if (Q.Reward.Xp > 0) { AddXp(Q.Reward.Xp); }
	if (!Q.Next.IsEmpty()) { StartQuest(Q.Next); }
	CheckWin();
}

void UStarkRules::Event(const FString& Type, const FStarkEvent& Data)
{
	for (const FStarkQuestDef& Q : Def.Quests)
	{
		FStarkQuestProgress* P = Quests.Find(Q.Id);
		if (!P || P->State != TEXT("active")) { continue; }
		const FStarkQuestStep* S = CurrentStep(Q);
		if (!S || S->Type != Type) { continue; }
		if (S->Level >= 0 && S->Level != LevelIndex) { continue; }
		bool bOk = false;
		int32 Add = 1;
		if (Type == TEXT("collect")) { bOk = S->Item == Data.Item; Add = FMath::Max(1, Data.N); }
		else if (Type == TEXT("defeat"))
		{
			if (IsMinor(Data.Id) || IsMinor(S->Id)) { continue; }     // child-safety: never a defeat target
			bOk = (S->Kind.IsEmpty() || S->Kind == TEXT("any") || S->Kind == Data.Kind) && (S->Id.IsEmpty() || S->Id == Data.Id);
		}
		else if (Type == TEXT("talk") || Type == TEXT("escort")) { bOk = S->Npc == Data.Npc; }
		else if (Type == TEXT("reach"))
		{
			const float R = S->R > 0.f ? S->R : 3.f;
			bOk = FVector2D(Data.X - S->X, Data.Z - S->Z).Size() < R;
		}
		if (bOk)
		{
			P->N = FMath::Min(FMath::Max(1, S->Count), P->N + Add);
			CheckStep(Q);
		}
	}
}

FString UStarkRules::StepText(const FStarkQuestStep& S) const
{
	if (!S.Text.IsEmpty()) { return S.Text; }
	const int32 C = FMath::Max(1, S.Count);
	const FString Num = C > 1 ? FString::Printf(TEXT(" (%d)"), C) : FString();
	if (S.Type == TEXT("collect")) { return TEXT("Collect ") + GetItem(S.Item).Name + Num; }
	if (S.Type == TEXT("defeat"))
	{
		FString Who = TEXT("enemies");
		if (!S.Id.IsEmpty()) { Who = EnemyName(S.Id); }
		else if (!S.Kind.IsEmpty() && S.Kind != TEXT("any")) { const FStarkEnemyDef* E = FindEnemy(S.Kind); Who = E ? E->Name : S.Kind; }
		return TEXT("Defeat ") + Who + Num;
	}
	if (S.Type == TEXT("talk")) { return TEXT("Talk to ") + NpcName(S.Npc); }
	if (S.Type == TEXT("escort")) { return TEXT("Escort ") + NpcName(S.Npc) + TEXT(" to ") + (S.Label.IsEmpty() ? TEXT("safety") : S.Label); }
	return TEXT("Reach ") + (S.Label.IsEmpty() ? TEXT("the marked spot") : S.Label);
}

TArray<const FStarkQuestDef*> UStarkRules::ActiveQuests() const
{
	TArray<const FStarkQuestDef*> Out;
	for (const FStarkQuestDef& Q : Def.Quests) { if (QuestState(Q.Id) == TEXT("active")) { Out.Add(&Q); } }
	return Out;
}

const FStarkQuestStep* UStarkRules::EscortStep(const FString& NpcId) const
{
	for (const FStarkQuestDef* Q : ActiveQuests())
	{
		const FStarkQuestStep* S = CurrentStep(*Q);
		if (S && S->Type == TEXT("escort") && S->Npc == NpcId) { return S; }
	}
	return nullptr;
}

bool UStarkRules::IsTalkTarget(const FString& NpcId) const
{
	for (const FStarkQuestDef* Q : ActiveQuests())
	{
		const FStarkQuestStep* S = CurrentStep(*Q);
		if (S && S->Type == TEXT("talk") && S->Npc == NpcId) { return true; }
	}
	return false;
}

bool UStarkRules::OffersQuest(const FString& NpcId) const
{
	return Def.Quests.ContainsByPredicate([&](const FStarkQuestDef& Q) { return Q.Giver == NpcId && !Quests.Contains(Q.Id); });
}

void UStarkRules::CheckWin()
{
	if (bWon || Def.Quests.Num() == 0) { return; }
	const bool bAnyFinal = Def.Quests.ContainsByPredicate([](const FStarkQuestDef& Q) { return Q.Final; });
	for (const FStarkQuestDef& Q : Def.Quests)
	{
		if ((!bAnyFinal || Q.Final) && QuestState(Q.Id) != TEXT("done")) { return; }
	}
	bWon = true;
	Score += 100;
	if (OnWin) { OnWin(); }
}

void UStarkRules::StartLevelQuests(int32 LevelIdx)
{
	LevelIndex = LevelIdx;
	for (const FStarkQuestDef& Q : Def.Quests)
	{
		if (Q.Auto && Q.Level == LevelIdx && !Quests.Contains(Q.Id)) { StartQuest(Q.Id); }
	}
	for (const FStarkQuestDef* Q : ActiveQuests()) { Foes(*Q); }
}

// ---------------------------------------------------------------- dialogue
bool UStarkRules::Cond(const FStarkCondition& C) const
{
	if (!C.Has.IsEmpty() && !Has(C.Has, FMath::Max(1, C.N))) { return false; }
	if (!C.Lacks.IsEmpty() && Has(C.Lacks)) { return false; }
	if (!C.Done.IsEmpty() && QuestState(C.Done) != TEXT("done")) { return false; }
	if (!C.Active.IsEmpty() && QuestState(C.Active) != TEXT("active")) { return false; }
	if (!C.NotStarted.IsEmpty() && Quests.Contains(C.NotStarted)) { return false; }
	if (!C.Flag.IsEmpty() && !Flags.Contains(C.Flag)) { return false; }
	if (C.MinLevel > 0 && Lvl < C.MinLevel) { return false; }
	return true;
}

void UStarkRules::Act(const FStarkAction& A)
{
	if (!A.Take.IsEmpty()) { Take(A.Take, FMath::Max(1, A.TakeCount)); }
	for (const FString& G : A.Give) { Give(G, 1); }
	if (A.Gold != 0) { Gold += A.Gold; Toast(FString::Printf(TEXT("%s%d gold"), A.Gold > 0 ? TEXT("+") : TEXT(""), A.Gold)); }
	if (!A.Start.IsEmpty()) { StartQuest(A.Start); }
	if (!A.Advance.IsEmpty()) { FStarkEvent E; E.Npc = A.Advance; Event(TEXT("talk"), E); }
	if (!A.Flag.IsEmpty()) { Flags.Add(A.Flag); }
	if (A.Xp > 0) { AddXp(A.Xp); }
	if (A.Heal) { Hp = (float)Stats().MaxHp; }
	if (!A.Complete.IsEmpty())
	{
		const FStarkQuestDef* Q = FindQuest(A.Complete);
		if (Q && QuestState(A.Complete) == TEXT("active")) { CompleteQuest(*Q); }
	}
	if (A.Win && !bWon) { bWon = true; Score += 100; if (OnWin) { OnWin(); } }
}

void UStarkRules::Talk(const FString& NpcId, const FString& DialogId, const FString& Name, const FString& FallbackLine)
{
	FStarkEvent E;
	E.Npc = NpcId;
	Event(TEXT("talk"), E);
	DialogueNpcName = Name;
	const FStarkDialogueDef* D = FindDialogue(DialogId);
	if (!D)
	{
		ActiveDialogue = FStarkDialogueDef();
		FStarkDialogueNode N;
		N.Id = TEXT("a");
		N.Speaker = Name;
		N.Text = FallbackLine.IsEmpty() ? TEXT("Lovely day for an adventure, isn't it?") : FallbackLine;
		ActiveDialogue.Nodes.Add(N);
		ShowNode(TEXT("a"));
		return;
	}
	ActiveDialogue = *D;
	FString Start = D->Start;
	if (Start.IsEmpty() && D->Nodes.Num() > 0) { Start = D->Nodes[0].Id; }
	for (const FStarkDialogueBranch& B : D->Branches)
	{
		const bool bNodeExists = D->Nodes.ContainsByPredicate([&B](const FStarkDialogueNode& N) { return N.Id == B.Node; });
		if ((!B.HasRequires || Cond(B.Requires)) && bNodeExists) { Start = B.Node; break; }
	}
	ShowNode(Start);
}

void UStarkRules::ShowNode(const FString& InNodeId)
{
	const FStarkDialogueNode* N = ActiveDialogue.Nodes.FindByPredicate([&InNodeId](const FStarkDialogueNode& X) { return X.Id == InNodeId; });
	if (!N) { CloseDialogue(); return; }
	const FStarkDialogueNode Node = *N;          // Act() may start quests that change state; keep a copy
	NodeId = InNodeId;
	Act(Node.Action);
	VisibleChoices.Reset();
	for (const FStarkChoice& C : Node.Choices)
	{
		if (!C.HasRequires || Cond(C.Requires)) { VisibleChoices.Add(C); }
	}
	if (VisibleChoices.Num() == 0)
	{
		FStarkChoice C;
		C.Text = Node.Next.IsEmpty() ? TEXT("Farewell") : TEXT("Continue");
		C.Goto = Node.Next;
		C.End = Node.Next.IsEmpty();
		VisibleChoices.Add(C);
	}
	Speaker = !Node.Speaker.IsEmpty() ? Node.Speaker : (!DialogueNpcName.IsEmpty() ? DialogueNpcName : TEXT("Stranger"));
	Line = Node.Text;
	bDialogueOpen = true;
}

void UStarkRules::Choose(int32 Index)
{
	if (!bDialogueOpen || !VisibleChoices.IsValidIndex(Index)) { return; }
	const FStarkChoice C = VisibleChoices[Index];
	Act(C.Action);
	if (!C.Goto.IsEmpty() && !C.End) { ShowNode(C.Goto); } else { CloseDialogue(); }
}

void UStarkRules::CloseDialogue()
{
	bDialogueOpen = false;
	VisibleChoices.Reset();
	Line.Reset();
	Speaker.Reset();
}
